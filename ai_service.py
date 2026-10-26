"""Google Gemini REST integration. No API key is stored in source code.

The model drafts questions and learning feedback only. Scoring is deterministic
Python logic in app.py; all generated questions require teacher approval.
"""
import json
import requests
from config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_FALLBACK_MODELS


class AIServiceError(RuntimeError):
    pass


class AIConfigurationError(AIServiceError):
    pass


class GeminiService:
    API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models/"

    def __init__(self, api_key=None, model=None, http=requests, fallback_models=None):
        self.api_key = (api_key if api_key is not None else GEMINI_API_KEY).strip()
        self.model = model or GEMINI_MODEL
        self.fallback_models = tuple(fallback_models if fallback_models is not None else GEMINI_FALLBACK_MODELS)
        self.last_model = self.model
        self.http = http

    @property
    def configured(self):
        return bool(self.api_key)

    def _generate_json(self, prompt, schema, temperature=0.4):
        if not self.configured:
            raise AIConfigurationError(
                "Gemini is not configured. Set GEMINI_API_KEY in your local .env file; "
                "no simulated AI response was used."
            )
        models = []
        for model in (self.model, *self.fallback_models):
            if model and model not in models:
                models.append(model)
        body = {
            "systemInstruction": {"parts": [{"text": (
                "You are a careful university assessment assistant. Be accurate, concise, "
                "and return only the structured content requested."
            )}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        response = None
        for index, model in enumerate(models):
            url = f"{self.API_ROOT}{model}:generateContent"
            try:
                candidate = self.http.post(
                    url,
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=body,
                    timeout=(8, 20),
                )
            except requests.Timeout as exc:
                if index + 1 < len(models):
                    continue
                raise AIServiceError("Gemini did not respond before the timeout on the configured or fallback models. Please retry shortly.") from exc
            except requests.RequestException as exc:
                raise AIServiceError("Could not reach Gemini from this server. Check its internet connection.") from exc

            # If the selected model is under high demand, try an enabled Gemini
            # fallback. No sample response is substituted; only a real API response
            # can be saved as a question or learning review.
            if candidate.status_code == 503 and index + 1 < len(models):
                continue
            if candidate.status_code != 200:
                try:
                    detail = candidate.json().get("error", {}).get("message", "")
                except (ValueError, AttributeError):
                    detail = ""
                if candidate.status_code in (401, 403):
                    message = "Gemini rejected the API key. Check that GEMINI_API_KEY is valid."
                elif candidate.status_code == 404:
                    message = f"Model '{model}' was not found. Set GEMINI_MODEL to an enabled model."
                elif candidate.status_code == 429:
                    message = "Gemini rate limit reached. Wait briefly, then retry."
                elif candidate.status_code >= 500:
                    message = "Gemini is temporarily unavailable after trying the configured fallback models."
                else:
                    message = f"Gemini returned HTTP {candidate.status_code}."
                if detail:
                    message += " " + detail[:220]
                raise AIServiceError(message)
            response = candidate
            self.last_model = model
            break

        if response is None:
            raise AIServiceError("Gemini is temporarily unavailable. Please retry in a moment.")
        try:
            payload = response.json()
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts).strip()
            return json.loads(text)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIServiceError("Gemini returned a response that could not be read as the requested JSON.") from exc

    def generate_questions(self, subject, topic, difficulty, count):
        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "question": {"type": "STRING"},
                    "options": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "correctIndex": {"type": "INTEGER"},
                    "topic": {"type": "STRING"},
                    "explanation": {"type": "STRING"},
                },
                "required": ["question", "options", "correctIndex", "topic", "explanation"],
            },
        }
        prompt = (
            f"Create exactly {count} multiple-choice questions for a college exam.\n"
            f"Subject: {subject}\nTopic: {topic}\nDifficulty: {difficulty}\n"
            "Each question must have exactly four distinct options and exactly one correct answer. "
            "Do not use 'all of the above' or 'none of the above'. Give a concise explanation. "
            "correctIndex is zero-based (0 to 3). Questions must be clear, technically accurate, "
            "and appropriate for a student. Return the array only."
        )
        data = self._generate_json(prompt, schema, temperature=0.7)
        if not isinstance(data, list):
            raise AIServiceError("Gemini did not return a question list.")
        valid = []
        for item in data[:count]:
            try:
                q = self.validate_question(item)
                q["topic"] = (str(item.get("topic") or topic).strip()[:100] or topic)
                q["explanation"] = str(item.get("explanation", "")).strip()[:2000]
                valid.append(q)
            except (ValueError, TypeError, AttributeError):
                continue
        if not valid:
            raise AIServiceError("Gemini returned no usable questions. Try another topic or retry.")
        return valid

    @staticmethod
    def validate_question(item):
        if not isinstance(item, dict):
            raise ValueError("question must be an object")
        text = str(item.get("question", "")).strip()
        options = item.get("options")
        idx = item.get("correctIndex")
        if not text or not isinstance(options, list) or len(options) != 4:
            raise ValueError("question and four options are required")
        options = [str(x).strip() for x in options]
        if any(not x for x in options) or len({x.casefold() for x in options}) != 4:
            raise ValueError("options must be non-empty and distinct")
        if isinstance(idx, bool) or not isinstance(idx, int) or idx not in range(4):
            raise ValueError("correctIndex must be between zero and three")
        return {
            "question_text": text[:5000],
            "options": options,
            "correct_option": "ABCD"[idx],
        }

    def generate_feedback(self, exam, attempt, reviews):
        schema = {
            "type": "OBJECT",
            "properties": {
                "summary": {"type": "STRING"},
                "weakTopics": {"type": "ARRAY", "items": {"type": "STRING"}},
                "studyPlan": {"type": "ARRAY", "items": {"type": "STRING"}},
                "explanations": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "question": {"type": "STRING"},
                            "whyWrong": {"type": "STRING"},
                            "concept": {"type": "STRING"},
                        },
                        "required": ["question", "whyWrong", "concept"],
                    },
                },
            },
            "required": ["summary", "weakTopics", "studyPlan", "explanations"],
        }
        wrong = [r for r in reviews if not r["is_correct"]][:8]
        grounded = [
            {
                "question": r["question_text"],
                "topic": r["topic"],
                "student_answer": r["selected_text"] or "(blank)",
                "correct_answer": r["correct_text"],
                "teacher_note": r["explanation"] or "",
            }
            for r in wrong
        ]
        prompt = (
            "Write a supportive and specific post-exam learning report using only the supplied facts. "
            "Do not invent mistakes, facts, or scores. If there are no wrong answers, congratulate the student "
            "and suggest a next-level revision plan.\n"
            f"Exam: {exam['title']} ({exam['subject']})\n"
            f"Score: {attempt['score']} / {attempt['total_marks']} ({attempt['percentage']}%)\n"
            f"Incorrect answers (ground truth from the system): {json.dumps(grounded, ensure_ascii=False)}\n"
            "Return summary, up to four weakTopics, three to five concrete studyPlan actions, and one short "
            "explanation per supplied incorrect answer. Keep language encouraging and concise."
        )
        data = self._generate_json(prompt, schema, temperature=0.35)
        if not isinstance(data, dict) or not str(data.get("summary", "")).strip():
            raise AIServiceError("Gemini returned an incomplete learning report.")
        return {
            "summary": str(data["summary"])[:2000],
            "weakTopics": [str(x)[:100] for x in data.get("weakTopics", [])[:4]],
            "studyPlan": [str(x)[:300] for x in data.get("studyPlan", [])[:5]],
            "explanations": [
                {"question": str(x.get("question", ""))[:300],
                 "whyWrong": str(x.get("whyWrong", ""))[:500],
                 "concept": str(x.get("concept", ""))[:100]}
                for x in data.get("explanations", [])[:8] if isinstance(x, dict)
            ],
        }
