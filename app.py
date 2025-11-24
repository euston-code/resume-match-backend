from flask import Flask, request, jsonify
import os, json, requests

app = Flask(__name__)

@app.route("/match", methods=["POST"])
def match():
    data = request.get_json() or {}
    # Simple echo response for initial testing
    return jsonify({
        "message": "Webhook working!",
        "received": data
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
