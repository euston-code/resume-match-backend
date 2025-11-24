# app.py
# Webhook that accepts candidate/job JSON, extracts resume text (local path or URL),
# calls OpenAI Chat Completion to generate a structured match JSON, and returns it.
#
# Required env var: OPENAI_API_KEY

import os
import json
import requests
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

def read_local_file_text(path):
    """Try to read a local file as text. Return None on failure."""
    try:
        p = Path(path)
        if not p.exists():
            return None
        # try reading as text
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

def fetch_url_text(url):
    """Fetch a URL and return text if content-type is textual, else None."""
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        if "text" in ctype or "json" in ctype:
            return r.text
        return None
    except Exception:
        return None

def call_openai_match(resume_text, candidate_id, candidate_name, job_id, job_text, required_skills):
    """Call OpenAI and return parsed JSON result."""
    # schema we want
    schema = {
      "candidate_id": "string",
      "name": "string",
      "skills": ["string"],
      "experience_years": "number",
      "summary": "string",
      "match": {
        "job_id": "string",
        "semantic_score": "number",
        "skill_coverage": "number",
        "final_score": "number",
        "matched_skills": ["string"],
        "explanation": "string"
      }
    }

    prompt = f"""
You are a recruiter assistant. Return ONLY valid JSON (no explanation) matching this schema:
{json.dumps(schema)}

Inputs:
resume_text: \"\"\"{(resume_text or '')[:4000]}\"\"\"
candidate_id: {candidate_id}
candidate_name: \"\"\"{candidate_name}\"\"\"
job_id: {job_id}
job_text: \"\"\"{(job_text or '')[:2000]}\"\"\"
required_skills: {required_skills}

Rules:
- Fill fields exactly as in the schema.
- semantic_score and skill_coverage must be numbers between 0.0 and 1.0.
- final_score = round(0.7 * semantic_score + 0.3 * skill_coverage, 2)
- matched_skills = intersection of required_skills and skills found in resume (case-insensitive).
- summary: one short sentence.
Return only the JSON object.
"""
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a JSON-only resume->job matching assistant."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 800
    }
    r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    # best-effort parse
    return json.loads(text)

@app.route("/match", methods=["POST"])
def match():
    if OPENAI_KEY is None:
        return jsonify({"error": "OPENAI_API_KEY not set on server"}), 500

    body = request.get_json(force=True)
    candidate_id = body.get("candidate_id", "unknown")
    candidate_name = body.get("candidate_name", "")
    resume_url = body.get("resume_url", "")
    job_id = body.get("job_id", "JOB_000")
    job_text = body.get("job_text", "")
    required_skills = body.get("required_skills", [])

    # 1) try local path read (useful for testing with /mnt/data/...)
    resume_text = None
    if resume_url and resume_url.startswith("/mnt/data"):
        resume_text = read_local_file_text(resume_url)

    # 2) else try fetching URL
    if resume_text is None and resume_url and resume_url.startswith("http"):
        resume_text = fetch_url_text(resume_url)

    # 3) fallback
    if not resume_text:
        resume_text = "(Full resume text unavailable. Proceeding with job_text and limited info.)"

    # Call OpenAI to get the structured match JSON
    try:
        match_json = call_openai_match(resume_text, candidate_id, candidate_name, job_id, job_text, required_skills)
    except Exception as e:
        return jsonify({"error": "openai_error", "detail": str(e)}), 500

    # Map to the simplified fields Zoho expects
    out = {
        "candidate_id": candidate_id,
        "ai_fit_score": match_json.get("match", {}).get("final_score"),
        "ai_summary": match_json.get("summary"),
        "ai_matched_skills": match_json.get("match", {}).get("matched_skills", []),
        "raw_match": match_json
    }
    return jsonify(out)

if __name__ == "__main__":
    # Port binding: Render exposes port 8080; allow override with PORT env var
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
