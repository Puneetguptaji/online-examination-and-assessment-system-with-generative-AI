import json
import unittest
from ai_service import GeminiService, AIConfigurationError, AIServiceError


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
    def json(self): return self.payload


class FakeHTTP:
    def __init__(self, payload): self.payload = payload; self.last = None
    def post(self, url, **kwargs):
        self.last = (url, kwargs)
        return FakeResponse(self.payload)


class GeminiServiceTests(unittest.TestCase):
    def test_missing_key_fails_clearly_without_fake_output(self):
        service = GeminiService(api_key="", http=FakeHTTP({}))
        with self.assertRaises(AIConfigurationError) as err:
            service.generate_questions("Python", "lists", "Easy", 1)
        self.assertIn("no simulated AI response", str(err.exception))

    def test_question_validation_maps_correct_index(self):
        valid = {"question":"Which is immutable?", "options":["list","dict","set","tuple"],
                 "correctIndex":3, "topic":"Collections", "explanation":"Tuples cannot be changed."}
        result = GeminiService.validate_question(valid)
        self.assertEqual(result["correct_option"], "D")
        self.assertEqual(result["options"][3], "tuple")

    def test_rejects_duplicate_options(self):
        invalid = {"question":"Q?", "options":["same","same","x","y"], "correctIndex":0}
        with self.assertRaises(ValueError):
            GeminiService.validate_question(invalid)

    def test_parses_live_api_json_shape_and_sends_key_header(self):
        generated = [{"question":"What is len([1,2])?", "options":["1","2","3","4"],
                      "correctIndex":1, "topic":"Lists", "explanation":"Two items."}]
        api_payload = {"candidates":[{"content":{"parts":[{"text":json.dumps(generated)}]}}]}
        fake = FakeHTTP(api_payload)
        service = GeminiService(api_key="test-key-not-real", model="gemini-test", http=fake)
        result = service.generate_questions("Python", "lists", "Easy", 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["correct_option"], "B")
        url, kwargs = fake.last
        self.assertTrue(url.endswith("/gemini-test:generateContent"))
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "test-key-not-real")

    def test_retries_real_generation_on_a_high_demand_fallback_model(self):
        generated = [{"question":"What does range(2) produce?", "options":["0,1","1,2","0,1,2","2"],
                      "correctIndex":0, "topic":"Loops", "explanation":"range(2) yields zero and one."}]
        payload = {"candidates":[{"content":{"parts":[{"text":json.dumps(generated)}]}}]}

        class HighDemandThenSuccess:
            def __init__(self): self.urls=[]
            def post(self,url,**kwargs):
                self.urls.append(url)
                if len(self.urls)==1:
                    return FakeResponse({"error":{"message":"high demand"}},503)
                return FakeResponse(payload,200)

        fake=HighDemandThenSuccess()
        service=GeminiService(api_key="test",model="gemini-3.8-flash",
                              fallback_models=("gemini-3.6-flash",),http=fake)
        result=service.generate_questions("Python","loops","Easy",1)
        self.assertEqual(len(result),1)
        self.assertEqual(service.last_model,"gemini-3.6-flash")
        self.assertTrue(fake.urls[0].endswith("/gemini-3.8-flash:generateContent"))
        self.assertTrue(fake.urls[1].endswith("/gemini-3.6-flash:generateContent"))

    def test_tries_fallback_after_primary_model_timeout(self):
        generated = [{"question":"Which loop repeats while a condition is true?", "options":["for","while","try","with"],
                      "correctIndex":1, "topic":"Loops", "explanation":"A while loop repeats while its condition stays true."}]
        payload = {"candidates":[{"content":{"parts":[{"text":json.dumps(generated)}]}}]}

        class TimeoutThenSuccess:
            def __init__(self): self.calls=0
            def post(self,url,**kwargs):
                self.calls += 1
                if self.calls == 1: raise requests.Timeout('simulated timeout')
                return FakeResponse(payload,200)

        import requests
        fake=TimeoutThenSuccess()
        service=GeminiService(api_key="test",model="gemini-3.8-flash",
                              fallback_models=("gemini-3.6-flash",),http=fake)
        self.assertEqual(len(service.generate_questions("Python","loops","Easy",1)),1)
        self.assertEqual(service.last_model,"gemini-3.6-flash")
        self.assertEqual(fake.calls,2)

    def test_http_failure_is_not_silent(self):
        class Failure(FakeHTTP):
            def post(self, url, **kwargs):
                class Response:
                    status_code=429
                    def json(self): return {"error":{"message":"quota"}}
                return Response()
        service = GeminiService(api_key="test", http=Failure({}))
        with self.assertRaises(AIServiceError) as err:
            service.generate_questions("Python", "lists", "Easy", 1)
        self.assertIn("rate limit", str(err.exception))


if __name__ == "__main__":
    unittest.main()
