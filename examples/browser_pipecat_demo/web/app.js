const elements = {
  serviceStatus: document.querySelector("#service-status"),
  webrtcStatus: document.querySelector("#webrtc-status"),
  bridgeStatus: document.querySelector("#bridge-status"),
  asrTarget: document.querySelector("#asr-target"),
  startButton: document.querySelector("#start-button"),
  stopButton: document.querySelector("#stop-button"),
  errorMessage: document.querySelector("#error-message"),
  partialText: document.querySelector("#partial-text"),
  finalLog: document.querySelector("#final-log"),
  eventLog: document.querySelector("#event-log"),
};

const state = {
  localStream: null,
  peerConnection: null,
  isStarting: false,
};

function setText(node, value) {
  node.textContent = value;
}

function logEvent(message) {
  const item = document.createElement("li");
  const time = new Date().toLocaleTimeString();
  item.textContent = `${time} - ${message}`;
  elements.eventLog.prepend(item);
}

function showError(message) {
  elements.errorMessage.hidden = false;
  setText(elements.errorMessage, message);
}

function clearError() {
  elements.errorMessage.hidden = true;
  setText(elements.errorMessage, "");
}

function renderControls() {
  elements.startButton.disabled = state.isStarting || Boolean(state.localStream);
  elements.stopButton.disabled = !state.localStream && !state.peerConnection;
}

function hasWebRTCSupport() {
  return Boolean(
    navigator.mediaDevices?.getUserMedia &&
      window.RTCPeerConnection &&
      window.RTCSessionDescription
  );
}

async function loadConfig() {
  try {
    const response = await fetch("/rtc-asr/config");
    if (!response.ok) {
      throw new Error(`Config request failed with ${response.status}`);
    }
    const config = await response.json();
    setText(elements.serviceStatus, "reachable");
    setText(elements.bridgeStatus, config.bridge_status);
    setText(elements.asrTarget, config.rtc_asr_ws_url);
    logEvent("Loaded demo service config.");
  } catch (error) {
    setText(elements.serviceStatus, "unreachable");
    showError(error.message);
    logEvent("Could not load demo service config.");
  }
}

async function startDemo() {
  clearError();

  if (!hasWebRTCSupport()) {
    setText(elements.webrtcStatus, "unsupported");
    showError("This browser does not expose the WebRTC APIs required for the demo.");
    return;
  }

  state.isStarting = true;
  renderControls();
  setText(elements.webrtcStatus, "requesting microphone");
  logEvent("Requesting microphone permission.");

  try {
    state.localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    state.peerConnection = new RTCPeerConnection();

    for (const track of state.localStream.getTracks()) {
      state.peerConnection.addTrack(track, state.localStream);
    }

    state.peerConnection.addEventListener("connectionstatechange", () => {
      setText(elements.webrtcStatus, state.peerConnection.connectionState);
      logEvent(`Peer connection state: ${state.peerConnection.connectionState}.`);
    });

    const offer = await state.peerConnection.createOffer();
    await state.peerConnection.setLocalDescription(offer);
    setText(elements.webrtcStatus, "signaling");
    logEvent("Created browser SDP offer.");

    const response = await fetch("/rtc-asr/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: offer.type,
        sdp: offer.sdp,
      }),
    });
    const payload = await response.json();

    if (!response.ok) {
      const detail = payload.detail || {};
      const message = detail.message || `Offer failed with ${response.status}`;
      setText(elements.bridgeStatus, detail.bridge_status || "error");
      showError(message);
      logEvent(`${detail.error || "SIGNALING_ERROR"}: ${message}`);
      return;
    }

    await state.peerConnection.setRemoteDescription(
      new RTCSessionDescription({ type: payload.type, sdp: payload.sdp })
    );
    setText(elements.webrtcStatus, "connected");
    setText(elements.bridgeStatus, payload.state);
    setText(elements.partialText, "Connected. Waiting for transcript events.");
    logEvent("Applied remote SDP answer.");
  } catch (error) {
    setText(elements.webrtcStatus, "error");
    showError(error.message);
    logEvent(`Start failed: ${error.message}`);
  } finally {
    state.isStarting = false;
    renderControls();
  }
}

function stopDemo() {
  clearError();

  if (state.peerConnection) {
    state.peerConnection.close();
    state.peerConnection = null;
  }

  if (state.localStream) {
    for (const track of state.localStream.getTracks()) {
      track.stop();
    }
    state.localStream = null;
  }

  setText(elements.webrtcStatus, "idle");
  setText(elements.partialText, "Waiting for a Pipecat bridge.");
  logEvent("Stopped local media and peer connection.");
  renderControls();
}

elements.startButton.addEventListener("click", startDemo);
elements.stopButton.addEventListener("click", stopDemo);

if (!hasWebRTCSupport()) {
  elements.startButton.disabled = true;
  setText(elements.webrtcStatus, "unsupported");
  showError("This browser does not expose the WebRTC APIs required for the demo.");
}

renderControls();
loadConfig();

