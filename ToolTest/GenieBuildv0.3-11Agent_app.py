# app.py (or whatever you name your main script)
import os
from flask import Flask, request, jsonify
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
import requests
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

app = Flask(__name__)
app.config['SSL_BUFFER_SIZE'] = 1024 * 1024  # 1MB buffer

# Environment variables (replace with your actual values)
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_AGENT_ID = "m0O5lZbgAeBBLigv4s64"
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")  # Your Twilio phone number

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def elevenlabs_get_next_message(agent_id, user_message=None, conversation_state=None):
    """
    Sends a message to the ElevenLabs Conversational AI agent and retrieves the response.
    """
    url = f"https://api.elevenlabs.io/v1/agents/{agent_id}/stream"
    headers = {
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }
    data = {}
    if user_message:
        data["message"] = user_message
    if conversation_state:
        data["conversation_state"] = conversation_state

    try:
        response = requests.post(url, headers=headers, json=data, stream=True)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        full_response = b""
        for chunk in response.iter_content(chunk_size=None):
            if chunk:
                full_response += chunk

        # Attempt to parse the full response as JSON
        try:
            json_response = full_response.decode("utf-8")
            json_response = json.loads(json_response)
            next_message = json_response["output"]["text"]
            conversation_state = json_response["conversation_state"]

        except (json.JSONDecodeError, KeyError) as e:
            print(f"JSON Decode Error: {e}")
            print(f"Raw response content: {full_response}")
            return None, None

        return next_message, conversation_state

    except requests.exceptions.RequestException as e:
        print(f"ElevenLabs API request failed: {e}")
        return None, None


@app.route("/twilio/inbound_call", methods=['POST'])
def inbound_call():
    """
    Handles incoming calls to the Twilio number.
    """
    print("Received inbound call")
    # Get the caller's message (if any)
    user_message = request.form.get('SpeechResult')
    if not user_message:
        user_message = request.form.get('Digits')  #Check for DTMF input

    # Get the current conversation state, or initialize it if it's a new call
    conversation_state = request.cookies.get("conversation_state")

    # Get the next message from ElevenLabs
    agent_response, new_conversation_state = elevenlabs_get_next_message(
        ELEVENLABS_AGENT_ID, user_message, conversation_state
    )

    # Create a TwiML response
    response = VoiceResponse()

    if agent_response:
        response.say(agent_response, voice='Polly.Joanna-Neural')  #Using Polly Neural voice.  Change if needed

    # Gather user input (speech or DTMF) for the next turn.
    gather = Gather(input_type='speech dtmf', timeout=3, action='/twilio/inbound_call')
    response.append(gather)

    # Store the updated conversation state in a cookie
    response_str = str(response)  # Get the TwiML as a string
    resp = app.make_response(response_str)  # Create a Flask response object
    if new_conversation_state:
        resp.set_cookie('conversation_state', new_conversation_state)  # Set the cookie
    resp.headers["Content-Type"] = "application/xml" #Set content type for Twilio

    return resp


@app.route("/outbound-call", methods=['POST'])
def outbound_call():
    """
    Initiates an outbound call.
    """
    print("Initiating outbound call")
    data = request.get_json()
    phone_number = data.get("number")
    prompt = data.get("prompt")
    first_message = data.get("first_message")

    if not phone_number or not prompt or not first_message:
        return jsonify({"error": "Missing phone number, prompt, or first message"}), 400

    try:
        #ElevenLabs does the converstaional part.  We just initiate the call and pass control to /inbound_call
        call = twilio_client.calls.create(
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
            url=request.url_root + "twilio/inbound_call", # Point to your inbound call route
            status_callback=request.url_root + "twilio/call_status", #Optional status callback
            status_callback_event=['initiated', 'ringing', 'answered', 'completed']
        )
        print(f"Call SID: {call.sid}")
        return jsonify({"message": "Outbound call initiated", "call_sid": call.sid}), 200

    except Exception as e:
        print(f"Error initiating outbound call: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/twilio/call_status", methods=['POST'])
def call_status():
    """
    Handle the status of the call (optional).
    """
    call_sid = request.values.get('CallSid')
    call_status = request.values.get('CallStatus')
    print(f"Call SID: {call_sid} is {call_status}")
    return '', 200


if __name__ == "__main__":
    import json
    app.run(debug=True, port=8000)  #Run on port 8000, as the JS example suggests

