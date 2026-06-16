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
  dataChannel: null,
  sessionId: null,
  pcId: null,
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

function appendFinalTranscript(text) {
  const item = document.createElement("li");
  const time = new Date().toLocaleTimeString();
  item.textContent = text ? `${time} - ${text}` : `${time} - [final transcript event]`;
  elements.finalLog.prepend(item);
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

function setupDataChannel(peerConnection) {
  const channel = peerConnection.createDataChannel("rtc-asr-transcripts");
  state.dataChannel = channel;

  channel.addEventListener("open", () => {
    setText(elements.bridgeStatus, "data channel open");
    logEvent("Transcript data channel opened.");
  });
  channel.addEventListener("close", () => {
    logEvent("Transcript data channel closed.");
  });
  channel.addEventListener("error", () => {
    setText(elements.bridgeStatus, "data channel error");
    showError("Transcript data channel reported an error.");
    logEvent("Transcript data channel error.");
  });
  channel.addEventListener("message", handleDataChannelMessage);
}

function handleDataChannelMessage(event) {
  let message;
  try {
    message = JSON.parse(event.data);
  } catch (error) {
    setText(elements.bridgeStatus, "message error");
    showError("Received a malformed transcript message.");
    logEvent(`Malformed data channel message: ${error.message}`);
    return;
  }

  if (!message || typeof message.type !== "string") {
    setText(elements.bridgeStatus, "message error");
    showError("Received a transcript message without a type.");
    logEvent("Received transcript message without a type.");
    return;
  }

  if (message.type === "partial") {
    setText(elements.partialText, message.text || "");
    setText(elements.bridgeStatus, "receiving partials");
    return;
  }

  if (message.type === "final") {
    appendFinalTranscript(message.text || "");
    setText(elements.partialText, "");
    setText(elements.bridgeStatus, "received final");
    return;
  }

  if (message.type === "error") {
    const errorMessage = message.message || message.text || "Bridge reported an error.";
    setText(elements.bridgeStatus, "error");
    setText(elements.partialText, errorMessage);
    showError(errorMessage);
    logEvent(`Bridge error: ${errorMessage}`);
    return;
  }

  if (message.type === "status") {
    const statusMessage = message.message || message.text || "Bridge status update.";
    setText(elements.bridgeStatus, statusMessage);
    logEvent(statusMessage);
    return;
  }

  logEvent(`Ignored data channel message type: ${message.type}.`);
}

function waitForIceGatheringComplete(peerConnection, timeoutMs = 3000) {
  if (peerConnection.iceGatheringState === "complete") {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    let timeoutId;

    function cleanup() {
      window.clearTimeout(timeoutId);
      peerConnection.removeEventListener("icegatheringstatechange", handleStateChange);
    }

    function handleStateChange() {
      logEvent(`ICE gathering state: ${peerConnection.iceGatheringState}.`);
      if (peerConnection.iceGatheringState === "complete") {
        cleanup();
        resolve();
      }
    }

    timeoutId = window.setTimeout(() => {
      cleanup();
      logEvent("Continuing after ICE gathering wait timeout.");
      resolve();
    }, timeoutMs);
    peerConnection.addEventListener("icegatheringstatechange", handleStateChange);
  });
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
    setupDataChannel(state.peerConnection);

    for (const track of state.localStream.getTracks()) {
      state.peerConnection.addTrack(track, state.localStream);
    }

    const peerConnection = state.peerConnection;
    peerConnection.addEventListener("connectionstatechange", () => {
      setText(elements.webrtcStatus, peerConnection.connectionState);
      logEvent(`Peer connection state: ${peerConnection.connectionState}.`);
    });

    const offer = await peerConnection.createOffer();
    await peerConnection.setLocalDescription(offer);
    setText(elements.webrtcStatus, "gathering ICE");
    logEvent("Created browser SDP offer.");
    await waitForIceGatheringComplete(peerConnection);

    const localDescription = peerConnection.localDescription;
    if (!localDescription) {
      throw new Error("Browser did not produce a local SDP offer.");
    }

    setText(elements.webrtcStatus, "signaling");
    const response = await fetch("/rtc-asr/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: localDescription.type,
        sdp: localDescription.sdp,
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

    state.sessionId = payload.session_id;
    state.pcId = payload.pc_id;
    await peerConnection.setRemoteDescription(
      new RTCSessionDescription({ type: payload.type, sdp: payload.sdp })
    );
    setText(elements.webrtcStatus, "connected");
    setText(elements.bridgeStatus, payload.state);
    setText(elements.partialText, "Connected. Waiting for transcript events.");
    logEvent(`Applied remote SDP answer for session ${state.sessionId}.`);
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

  if (state.dataChannel) {
    state.dataChannel.close();
    state.dataChannel = null;
  }

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

  state.sessionId = null;
  state.pcId = null;
  setText(elements.webrtcStatus, "idle");
  setText(elements.bridgeStatus, "stopped");
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
