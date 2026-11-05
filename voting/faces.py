"""Face embedding and matching.

Images arrive from the browser as base64 data URLs (a JPEG snapshot of the
webcam). For each one:

1. OpenCV's YuNet finds the face and five landmarks (eyes, nose, mouth corners).
2. DeepFace's MiniFASNet liveness check rejects photos and screens.
3. The face is aligned to the standard 112x112 ArcFace crop and InsightFace's
   ArcFace model (buffalo_l, w600k_r50, run with ONNX Runtime) turns it into a
   512-number embedding.

Embeddings are compared with cosine distance: 0 means identical, larger means
less alike.
"""

import base64
import binascii
import logging
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

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


DETECTOR_FILE = Path(__file__).parent / "face_models" / "face_detection_yunet_2023mar.onnx"
RECOGNITION_FILE = "w600k_r50.onnx"
RECOGNITION_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
# Where ArcFace expects the eyes, nose tip and mouth corners in its 112x112 input.
ARCFACE_POINTS = np.array(
    [[38.2946, 51.6963], [73.5318, 51.4800], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float32,
)
DETECT_MAX_SIDE = 640

_lock = threading.Lock()
_recognizer = None


def recognition_model_path():
    """Download the ArcFace model once (it ships inside InsightFace's 288 MB buffalo_l.zip)."""
    path = Path(settings.FACE_MODEL_DIR) / RECOGNITION_FILE
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.warning("Downloading the face recognition model (288 MB, once) to %s", path.parent)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        archive = Path(tmp) / "buffalo_l.zip"
        with urllib.request.urlopen(RECOGNITION_URL) as response, open(archive, "wb") as out:
            shutil.copyfileobj(response, out)
        with zipfile.ZipFile(archive) as z:
            member = next(n for n in z.namelist() if n.endswith(RECOGNITION_FILE))
            with z.open(member) as src, open(Path(tmp) / RECOGNITION_FILE, "wb") as out:
                shutil.copyfileobj(src, out)
        (Path(tmp) / RECOGNITION_FILE).replace(path)
    return path


def recognizer():
    global _recognizer
    with _lock:
        if _recognizer is None:
            import onnxruntime

            _recognizer = onnxruntime.InferenceSession(
                str(recognition_model_path()), providers=["CPUExecutionProvider"]
            )
    return _recognizer


def detect_faces(image):
    """Return YuNet detections for a BGR image as rows of
    [x, y, w, h, 5 landmark (x, y) pairs, score], in the image's own pixels."""
    import cv2

    try:  # errors only: OpenCV 5 warns about DNN targets on every detection
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except AttributeError:
        pass
    h, w = image.shape[:2]
    scale = min(1.0, DETECT_MAX_SIDE / max(h, w))
    small = cv2.resize(image, (round(w * scale), round(h * scale))) if scale < 1 else image
    # A detector per call: YuNet objects are cheap (230 KB) and not safe to share between threads.
    detector = cv2.FaceDetectorYN.create(str(DETECTOR_FILE), "", (small.shape[1], small.shape[0]), 0.8, 0.3, 5000)
    _, found = detector.detect(small)
    if found is None:
        return []
    return [np.concatenate([row[:14] / scale, row[14:]]) for row in found]


def check_liveness(image, face):
    """Raise SpoofError if DeepFace's MiniFASNet says the face is a photo or a screen."""
    from deepface.modules import modeling

    x, y, w, h = (int(v) for v in face[:4])
    model = modeling.build_model(task="spoofing", model_name="Fasnet")
    is_real, _score = model.analyze(img=image, facial_area=(x, y, w, h))
    if not is_real:
        raise SpoofError(
            "Liveness check failed. Look straight at the camera yourself; photos and screens are not accepted."
        )


def embed_face(image, face):
    """Align the face on its landmarks and return its unit-length ArcFace embedding."""
    import cv2

    landmarks = face[4:14].reshape(5, 2).astype(np.float32)
    matrix, _ = cv2.estimateAffinePartial2D(landmarks, ARCFACE_POINTS, method=cv2.LMEDS)
    crop = cv2.warpAffine(image, matrix, (112, 112), borderValue=0)
    blob = cv2.dnn.blobFromImage(crop, 1 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
    session = recognizer()
    embedding = session.run(None, {session.get_inputs()[0].name: blob})[0][0]
    return embedding / np.linalg.norm(embedding)


def get_embedding(data_url):
    """Return the embedding (list of floats) for the single face in the image."""
    image = decode_data_url(data_url)
    started = time.monotonic()
    try:
        faces = detect_faces(image)
        if not faces:
            raise FaceError(
                "No face was detected. Face the camera in good light, with your whole face inside the guide."
            )
        if len(faces) > 1:
            raise FaceError("More than one face was detected. Only the voter should be in the frame.")
        face = faces[0]
        if min(face[2], face[3]) < settings.FACE_MIN_SIZE:
            raise FaceError("Your face is too far from the camera. Move closer so it fills the guide.")
        if settings.FACE_ANTI_SPOOFING:
            check_liveness(image, face)
        return embed_face(image, face).tolist()
    finally:
        # Shown in the runserver window, to tell slow face scans from a slow network.
        logger.info("Face scan took %.1f s", time.monotonic() - started)


def warm_up():
    """Download and load the recognition and liveness models, so the first voter does not wait for them."""
    started = time.monotonic()
    recognizer()
    if settings.FACE_ANTI_SPOOFING:
        from deepface.modules import modeling

        modeling.build_model(task="spoofing", model_name="Fasnet")
    logger.info("Face models loaded in %.1f s", time.monotonic() - started)


def distance(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(1 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def combine(embeddings):
    """Average several photos of one face into one stored embedding.

    Returns (embedding, spread), where spread is the largest distance between any
    two of the photos. Raises FaceError when they disagree too much to trust.
    """
    spread = max(
        (distance(a, b) for i, a in enumerate(embeddings) for b in embeddings[i + 1:]),
        default=0.0,
    )
    if spread > settings.FACE_ENROL_CONSISTENCY:
        raise FaceError(
            "Your photos did not match each other well enough. Hold the phone steady at eye level, "
            "face a light, keep your whole face in the oval, and try again."
        )
    unit = [np.asarray(e, dtype=float) / np.linalg.norm(e) for e in embeddings]
    mean = np.mean(unit, axis=0)
    return (mean / np.linalg.norm(mean)).tolist(), spread


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
