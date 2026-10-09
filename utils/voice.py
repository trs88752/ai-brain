import speech_recognition as sr
import pyttsx3

engine = pyttsx3.init()

engine.setProperty("rate", 170)
engine.setProperty("volume", 1.0)


def speak(text):
    engine.say(text)
    engine.runAndWait()


def listen():
    recognizer = sr.Recognizer()

    with sr.Microphone() as source:
        print("Listening...")
        recognizer.adjust_for_ambient_noise(source, duration=1)

        try:
            audio = recognizer.listen(source, timeout=5)
            text = recognizer.recognize_google(audio)
            return text

        except sr.UnknownValueError:
            return "Sorry, I couldn't understand."

        except sr.RequestError:
            return "Speech service unavailable."

        except Exception as e:
            return f"Voice Error: {str(e)}"