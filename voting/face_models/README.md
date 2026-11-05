# Face models

- `face_detection_yunet_2023mar.onnx`: YuNet face detector from the
  [OpenCV Model Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet),
  MIT licence. Kept in the repository because it is small (230 KB).

The recognition model, InsightFace's ArcFace `w600k_r50.onnx` from the
[buffalo_l](https://github.com/deepinsight/insightface/tree/master/model_zoo) pack,
is 174 MB, so it is downloaded on first use to `FACE_MODEL_DIR`
(default `~/.unnvote/models`). InsightFace's pretrained models are for
non-commercial research use, which covers this project.
