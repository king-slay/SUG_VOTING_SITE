/*
 * Webcam capture for face registration and verification.
 *
 * Markup expected inside a <form> (see templates/voting/_camera.html):
 *   <div class="camera" data-camera>
 *     <video autoplay playsinline muted></video>
 *     ...guide overlay...
 *   </div>
 *   <p class="camera-status" data-camera-status></p>
 *   <li data-check="light">, <li data-check="face">   (optional live checks)
 *   <button type="button" data-capture>Capture</button>   (optional)
 *   <input type="hidden" name="face_image">
 *
 * With data-capture-on-submit on the form, a snapshot is taken automatically
 * when the form is submitted (used for the re-check on the ballot page).
 *
 * While the camera runs, a small frame is sampled twice a second to coach the
 * student: too dark, too bright, and (where the browser has FaceDetector)
 * no face, two faces, off centre, too far or too close. The camera box gets
 * data-state="good" or "warn" so the oval turns green or amber.
 */
(function () {
  function setStatus(el, text) { if (el) el.textContent = text; }

  function grab(video) {
    var canvas = document.createElement("canvas");
    var w = video.videoWidth, h = video.videoHeight;
    var scale = Math.min(1, 640 / Math.max(w, h));
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    var ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    var px = ctx.getImageData(0, 0, canvas.width, canvas.height).data, sum = 0;
    for (var i = 0; i < px.length; i += 40) sum += px[i] + px[i + 1] + px[i + 2];
    return { url: canvas.toDataURL("image/jpeg", 0.9), brightness: sum / (px.length / 40) / 3 };
  }

  // Browsers (Chrome on Android especially) pause a muted video that is scrolled
  // off screen, which gives a black snapshot. Bring the camera into view, make
  // sure it is playing, and wait for a fresh frame before grabbing it.
  function snapshot(box, video) {
    box.scrollIntoView({ block: "center", behavior: "instant" });
    return Promise.resolve(video.play()).catch(function () {}).then(function () {
      return new Promise(function (resolve) { setTimeout(resolve, 400); });
    }).then(function () {
      var shot = grab(video);
      if (shot.brightness < 15) throw new Error("dark");
      return shot.url;
    });
  }

  // Average brightness (0-255) of the middle of the frame, where the face should be.
  var probe = document.createElement("canvas");
  probe.width = 48; probe.height = 36;
  function centreBrightness(video) {
    var ctx = probe.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(video, 0, 0, probe.width, probe.height);
    var px = ctx.getImageData(14, 6, 20, 24).data, sum = 0;
    for (var i = 0; i < px.length; i += 4) sum += 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
    return sum / (px.length / 4);
  }

  var detector = null;
  if ("FaceDetector" in window) {
    try { detector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 3 }); } catch (e) { detector = null; }
  }

  // Returns a promise of { light: bool, face: bool|null, tip: string|null }.
  function assess(video) {
    var b = centreBrightness(video);
    var result = { light: b >= 60 && b <= 225, face: null, tip: null };
    if (b < 60) result.tip = "Too dark. Face a window or a light, not away from it.";
    else if (b > 225) result.tip = "Too bright. Move out of direct sunlight or away from the lamp.";
    if (!detector) return Promise.resolve(result);
    return detector.detect(video).then(function (faces) {
      var w = video.videoWidth, h = video.videoHeight;
      if (faces.length === 0) { result.face = false; result.tip = result.tip || "We can't see a face. Look straight at the camera."; }
      else if (faces.length > 1) { result.face = false; result.tip = "Only one person should be in view."; }
      else {
        var f = faces[0].boundingBox, cx = (f.x + f.width / 2) / w, cy = (f.y + f.height / 2) / h, size = f.width / w;
        result.face = true;
        if (size < 0.22) { result.face = false; result.tip = result.tip || "Move a little closer."; }
        else if (size > 0.6) { result.face = false; result.tip = result.tip || "Move back a little."; }
        else if (Math.abs(cx - 0.5) > 0.14 || Math.abs(cy - 0.46) > 0.16) { result.face = false; result.tip = result.tip || "Move your face to the centre of the oval."; }
      }
      return result;
    }, function () { return result; });
  }

  function setup(form) {
    var box = form.querySelector("[data-camera]");
    var video = box.querySelector("video");
    var status = form.querySelector("[data-camera-status]");
    var captureBtn = form.querySelector("[data-capture]");
    var input = form.querySelector("input[name=face_image]");
    var submitBtn = form.querySelector("[type=submit]");
    var checks = {
      light: form.querySelector('[data-check="light"]'),
      face: form.querySelector('[data-check="face"]')
    };
    var submitLabel = submitBtn ? submitBtn.textContent : "";
    var readyText = captureBtn
      ? "Position your face inside the oval, then press Capture."
      : "Keep your face inside the oval while you vote.";
    var preview = null;
    var ready = false;
    var busy = false;
    // While a message is on hold, the live coach does not replace it.
    var holdUntil = 0;
    function hold() { holdUntil = Date.now() + 4000; }

    function setState(state) { box.setAttribute("data-state", state); }
    function mark(el, ok) {
      if (!el) return;
      if (ok === null) el.removeAttribute("data-ok");
      else el.setAttribute("data-ok", ok ? "yes" : "no");
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setState("error");
      setStatus(status, "This browser cannot use the camera. Use a recent Chrome, Edge, Safari or Firefox, over https.");
      if (submitBtn) submitBtn.disabled = true;
      return;
    }

    function coach() {
      if (!ready || preview || busy || document.hidden || Date.now() < holdUntil) return;
      // An off-screen muted video may be paused with no frame yet; don't
      // call that "too dark".
      if (video.paused) { Promise.resolve(video.play()).catch(function () {}); return; }
      if (video.readyState < 2) return;
      assess(video).then(function (r) {
        if (!ready || preview || busy) return;
        mark(checks.light, r.light);
        mark(checks.face, r.face);
        if (!r.light || r.face === false) {
          setState("warn");
          setStatus(status, r.tip);
        } else if (r.face === null) {
          // This browser can't detect faces (most Android phones), so only the
          // light was checked. Stay neutral rather than green; the server checks
          // for a real, live face when the form is sent.
          setState("live");
          setStatus(status, "Light looks good. " + readyText);
        } else {
          setState("good");
          setStatus(status, readyText);
        }
      });
    }

    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
      .then(function (stream) {
        video.srcObject = stream;
        video.onloadedmetadata = function () {
          ready = true;
          setState("live");
          setStatus(status, readyText);
          setInterval(coach, 500);
        };
      })
      .catch(function () {
        setState("error");
        setStatus(status, "Camera access was blocked. Allow camera access in your browser settings and reload the page.");
        if (submitBtn) submitBtn.disabled = true;
      });

    function clearPreview() {
      if (preview) { preview.remove(); preview = null; }
      input.value = "";
    }

    function tooDark() {
      hold();
      setState("warn");
      setStatus(status, "The picture is too dark. Move to better light, keep the camera uncovered, and try again.");
    }

    function flash() {
      box.classList.remove("flashing");
      void box.offsetWidth;
      box.classList.add("flashing");
    }

    if (captureBtn) {
      captureBtn.addEventListener("click", function () {
        if (!ready) return;
        if (preview) {
          clearPreview();
          captureBtn.textContent = "Capture";
          setState("live");
          setStatus(status, readyText);
          return;
        }
        busy = true;
        snapshot(box, video).then(function (url) {
          busy = false;
          input.value = url;
          preview = document.createElement("img");
          preview.src = url;
          preview.alt = "Captured photo";
          box.appendChild(preview);
          flash();
          setState("captured");
          captureBtn.textContent = "Retake";
          setStatus(status, "Photo captured. Retake it if your face is blurred or not centred.");
        }, function () { busy = false; tooDark(); });
      });
    }

    function lock() {
      busy = true;
      setState("verifying");
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Verifying your face...";
      }
    }

    form.addEventListener("submit", function (event) {
      if (input.value && !form.hasAttribute("data-capture-on-submit")) {
        lock();
        return;
      }
      // No photo captured yet, or the ballot page, which always re-checks the face at
      // the moment of submitting: take the photo now instead of sending the voter back.
      event.preventDefault();
      if (!form.reportValidity()) return;
      if (!ready) {
        hold();
        setStatus(status, "Waiting for the camera to start...");
        return;
      }
      lock();
      snapshot(box, video).then(function (url) {
        input.value = url;
        flash();
        form.submit();
      }, function () {
        busy = false;
        tooDark();
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = submitLabel; }
      });
    });
  }

  document.querySelectorAll("form[data-face-form]").forEach(setup);
})();
