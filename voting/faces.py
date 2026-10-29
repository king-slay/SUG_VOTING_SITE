"""Face embedding and matching, built on DeepFace + OpenCV.

Images arrive from the browser as base64 data URLs (a JPEG snapshot of the
webcam). We turn each into a numeric embedding and compare embeddings with
cosine distance: 0 means identical, larger means less alike.
"""

import base64
import binascii
import logging
import time

import numpy as np
from django.conf import settings


logger = logging.getLogger(__name__)


class FaceError(Exception):
    """A user-facing problem with the captured image (no face, two faces, spoof...)."""


class SpoofError(FaceError):
    """The liveness check thinks the camera is looking at a photo or screen, not a live face."""


def decode_data_url(data_url):
    """Return an OpenCV BGR image from a 'data:image/jpeg;base64,...' string."""
    import cv2

    if not data_url:
        raise FaceError("No photo was captured. Please allow camera access and try again.")
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    try:
        raw = base64.b64decode(data_url, validate=True)
    except (binascii.Error, ValueError):
        raise FaceError("The captured photo could not be read. Please try again.")
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FaceError("The captured photo could not be read. Please try again.")
    return image


def get_embedding(data_url):
    """Return the embedding (list of floats) for the single face in the image."""
    from deepface import DeepFace

    image = decode_data_url(data_url)
    started = time.monotonic()
    try:
        faces = DeepFace.represent(
            img_path=image,
            model_name=settings.FACE_MODEL,
            detector_backend=settings.FACE_DETECTOR,
            enforce_detection=True,
            anti_spoofing=settings.FACE_ANTI_SPOOFING,
        )
    except ValueError as exc:
        message = str(exc).lower()
        if "spoof" in message:
            raise SpoofError(
                "Liveness check failed. Look straight at the camera yourself; photos and screens are not accepted."
            )
        if "face could not be detected" in message:
            raise FaceError(
                "No face was detected. Face the camera in good light, with your whole face inside the guide."
            )
        raise  # a setup problem (e.g. model download failed), not the voter's fault
    finally:
        # Shown in the runserver window, to tell slow face scans from a slow network.
        logger.info("Face scan took %.1f s", time.monotonic() - started)
    if len(faces) != 1:
        raise FaceError("More than one face was detected. Only the voter should be in the frame.")
    return faces[0]["embedding"]


def warm_up():
    """Load the detector, recognition and liveness models, so the first voter does not wait for them."""
    from deepface import DeepFace

    started = time.monotonic()
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    try:
        DeepFace.represent(
            img_path=blank, model_name=settings.FACE_MODEL, detector_backend=settings.FACE_DETECTOR,
            enforce_detection=False, anti_spoofing=settings.FACE_ANTI_SPOOFING,
        )
    except ValueError:
        pass  # a blank frame may be flagged as a spoof; the models are loaded either way
    logger.info("Face models loaded in %.1f s", time.monotonic() - started)


def distance(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(1 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def matches(stored_embedding, new_embedding):
    """Return (is_match, distance)."""
    d = distance(stored_embedding, new_embedding)
    return d <= settings.FACE_MATCH_THRESHOLD, d


def nearest_face(new_embedding, voters):
    """Return (voter, distance) for the registered face closest to new_embedding, or (None, None)."""
    best, best_dist = None, None
    for voter in voters:
        if voter.face_embedding:
            d = distance(voter.face_embedding, new_embedding)
            if best_dist is None or d < best_dist:
                best, best_dist = voter, d
    return best, best_dist


def find_duplicate(new_embedding, voters):
    """Return (voter, distance) if new_embedding is too close to a registered face, else (None, distance)."""
    voter, d = nearest_face(new_embedding, voters)
    if voter is not None and d <= settings.FACE_DUPLICATE_THRESHOLD:
        return voter, d
    return None, d
