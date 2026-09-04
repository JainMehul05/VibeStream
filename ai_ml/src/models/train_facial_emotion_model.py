import os
import pickle

import librosa
import numpy as np
from moviepy.editor import AudioFileClip
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC


# Resolve paths relative to the repository root.
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)

DATASET_PATH = os.path.join(
    PROJECT_ROOT,
    "ai_ml",
    "data",
)

MODEL_SAVE_PATH = os.path.join(
    PROJECT_ROOT,
    "ai_ml",
    "models",
    "speech_emotion_model",
)

os.makedirs(MODEL_SAVE_PATH, exist_ok=True)


# Define the list of emotions we're interested in.
emotion_labels = {
    "01": "neutral",
    "02": "calm",
    "03": "happy",
    "04": "sad",
    "05": "angry",
    "06": "fearful",
    "07": "disgust",
    "08": "surprise",
}


def extract_features(file_name):
    """
    Extract MFCC features from an audio file using librosa.

    Handles both .wav and .mp4 files.

    :param file_name: Path to the audio file.
    :return: Extracted MFCC features or None if extraction fails.
    """
    temp_audio_path = None

    try:
        # Convert mp4 to wav when necessary.
        if file_name.endswith(".mp4"):
            audio_clip = AudioFileClip(file_name)
            temp_audio_path = os.path.join(
                os.path.dirname(file_name),
                "temp_audio.wav",
            )
            audio_clip.audio.write_audiofile(temp_audio_path)
            audio_clip.close()
            file_name = temp_audio_path

        audio_data, sample_rate = librosa.load(
            file_name,
            res_type="kaiser_fast",
        )

        mfccs = np.mean(
            librosa.feature.mfcc(
                y=audio_data,
                sr=sample_rate,
                n_mfcc=40,
            ).T,
            axis=0,
        )

        return mfccs

    except Exception as e:
        print(
            f"Error encountered while parsing file: {file_name}, "
            f"error: {str(e)}"
        )
        return None

    finally:
        if temp_audio_path and os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)


def load_data(dataset_path):
    """
    Load the dataset and extract features and labels.

    :param dataset_path: Path to the dataset directory.
    :return: Extracted features and labels.
    """
    X = []
    y = []

    for subdir, dirs, files in os.walk(dataset_path):
        for file in files:
            if file.endswith(".wav") or file.endswith(".mp4"):
                print(f"Processing file: {file}")

                # Extract emotion label from the RAVDESS filename.
                emotion_code = file.split("-")[2]
                emotion = emotion_labels.get(emotion_code)

                if emotion is not None:
                    feature = extract_features(
                        os.path.join(subdir, file)
                    )

                    if feature is not None:
                        X.append(feature)
                        y.append(emotion)
                else:
                    print(
                        f"Skipping file with unrecognized "
                        f"emotion code: {file}"
                    )

    print(f"Total samples loaded: {len(X)}")

    return np.array(X), np.array(y)


def train_speech_emotion_model(X, y):
    """
    Train a speech emotion recognition model using SVM.

    :param X: Features.
    :param y: Labels.
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
    )

    scaler = StandardScaler()

    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    model = SVC(
        kernel="linear",
        probability=True,
    )

    model.fit(X_train_scaled, y_train)

    y_pred = model.predict(X_test_scaled)

    print(
        "Training Accuracy:",
        accuracy_score(
            y_train,
            model.predict(X_train_scaled),
        ),
    )

    print(
        "Test Accuracy:",
        accuracy_score(y_test, y_pred),
    )

    print(
        "\nClassification Report:\n",
        classification_report(y_test, y_pred),
    )

    model_file_path = os.path.join(
        MODEL_SAVE_PATH,
        "trained_speech_emotion_model.pkl",
    )

    scaler_file_path = os.path.join(
        MODEL_SAVE_PATH,
        "scaler.pkl",
    )

    with open(model_file_path, "wb") as file:
        pickle.dump(model, file)

    with open(scaler_file_path, "wb") as file:
        pickle.dump(scaler, file)

    print(
        f"Model and scaler saved successfully in {MODEL_SAVE_PATH}."
    )


if __name__ == "__main__":
    print("Loading data...")

    X, y = load_data(DATASET_PATH)

    print(f"Loaded {len(X)} samples.")

    print("Training the model...")

    train_speech_emotion_model(X, y)

    print("Training completed.")