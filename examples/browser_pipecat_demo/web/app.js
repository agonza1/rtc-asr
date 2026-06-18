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
  sourceMic: document.querySelector("#source-mic"),
  sourceFile: document.querySelector("#source-file"),
  audioFileInput: document.querySelector("#audio-file-input"),
  sourceHelp: document.querySelector("#source-help"),
};

const state = {
  localStream: null,
  peerConnection: null,
  dataChannel: null,
  sessionId: null,
  pcId: null,
  isStarting: false,
  audioContext: null,
  audioElement: null,
  audioObjectUrl: null,
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

function currentSourceMode() {
  return elements.sourceFile.checked ? "file" : "mic";
}

function selectedAudioFile() {
  return elements.audioFileInput.files?.[0] || null;
}

function updateSourceHelp() {
  if (currentSourceMode() === "file") {
    const file = selectedAudioFile();
    setText(
      elements.sourceHelp,
      file
        ? `Uploaded clip: ${file.name}. This will play in real time from the browser over WebRTC.`
        : "Choose an audio clip to stream real-time browser audio over WebRTC without using a live microphone."
    );
    return;
  }

  setText(
    elements.sourceHelp,
    "Use a microphone for live speech or switch to an uploaded clip for repeatable real-time browser playback."
  );
}

function renderControls() {
  const hasSourceFile = Boolean(selectedAudioFile());
  const sourceMode = currentSourceMode();
  const isStreaming = Boolean(state.localStream) || Boolean(state.peerConnection);

  elements.audioFileInput.disabled = sourceMode !== "file" || state.isStarting || isStreaming;
  elements.sourceMic.disabled = state.isStarting || isStreaming;
  elements.sourceFile.disabled = state.isStarting || isStreaming;
  elements.startButton.disabled =
    state.isStarting || isStreaming || (sourceMode === "file" && !hasSourceFile);
  elements.stopButton.disabled = !isStreaming;
  elements.startButton.textContent = sourceMode === "file" ? "Start file stream" : "Start mic";
  updateSourceHelp();
}

function hasWebRTCSupport() {
  return Boolean(
    navigator.mediaDevices?.getUserMedia &&
      window.RTCPeerConnection &&
      window.RTCSessionDescription &&
      window.AudioContext
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

function waitForAudioReadiness(audioElement) {
  if (audioElement.readyState >= HTMLMediaElement.HAVE_ENOUGH_DATA) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    function cleanup() {
      audioElement.removeEventListener("canplaythrough", handleReady);
      audioElement.removeEventListener("error", handleError);
    }

    function handleReady() {
      cleanup();
      resolve();
    }

    function handleError() {
      cleanup();
      reject(new Error("The selected audio file could not be decoded for playback."));
    }

    audioElement.addEventListener("canplaythrough", handleReady, { once: true });
    audioElement.addEventListener("error", handleError, { once: true });
  });
}

async function buildFileStream() {
  const file = selectedAudioFile();
  if (!file) {
    throw new Error("Choose an audio file before starting file playback.");
  }

  const audioContext = new AudioContext();
  const destination = audioContext.createMediaStreamDestination();
  const audioElement = new Audio();
  const objectUrl = URL.createObjectURL(file);

  audioElement.src = objectUrl;
  audioElement.preload = "auto";
  audioElement.playsInline = true;
  audioElement.addEventListener("ended", () => {
    setText(elements.bridgeStatus, "playback complete");
    setText(elements.partialText, "Playback finished. If no final transcript appears automatically, click Stop to close the session.");
    logEvent("Uploaded file playback finished.");
  });

  const sourceNode = audioContext.createMediaElementSource(audioElement);
  sourceNode.connect(destination);

  await waitForAudioReadiness(audioElement);

  state.audioContext = audioContext;
  state.audioElement = audioElement;
  state.audioObjectUrl = objectUrl;
  return destination.stream;
}

async function startSourceStream() {
  if (currentSourceMode() === "file") {
    setText(elements.webrtcStatus, "preparing file playback");
    logEvent("Preparing uploaded audio file for browser playback.");
    return buildFileStream();
  }

  setText(elements.webrtcStatus, "requesting microphone");
  logEvent("Requesting microphone permission.");
  return navigator.mediaDevices.getUserMedia({ audio: true, video: false });
}

async function startPlaybackIfNeeded() {
  if (currentSourceMode() !== "file" || !state.audioElement || !state.audioContext) {
    return;
  }

  await state.audioContext.resume();
  await state.audioElement.play();
  logEvent("Started uploaded audio playback through the browser WebRTC track.");
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

  try {
    state.localStream = await startSourceStream();
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
      stopDemo(true);
      return;
    }

    state.sessionId = payload.session_id;
    state.pcId = payload.pc_id;
    await peerConnection.setRemoteDescription(
      new RTCSessionDescription({ type: payload.type, sdp: payload.sdp })
    );
    await startPlaybackIfNeeded();
    setText(elements.webrtcStatus, "connected");
    setText(elements.bridgeStatus, payload.state);
    setText(
      elements.partialText,
      currentSourceMode() === "file"
        ? "Connected. Uploaded audio is now streaming through the browser WebRTC track."
        : "Connected. Waiting for transcript events."
    );
    logEvent(`Applied remote SDP answer for session ${state.sessionId}.`);
  } catch (error) {
    setText(elements.webrtcStatus, "error");
    showError(error.message);
    logEvent(`Start failed: ${error.message}`);
    stopDemo(true);
    return;
  } finally {
    state.isStarting = false;
    renderControls();
  }
}

function resetPlaybackState() {
  if (state.audioElement) {
    state.audioElement.pause();
    state.audioElement.src = "";
    state.audioElement.load();
    state.audioElement = null;
  }

  if (state.audioContext) {
    state.audioContext.close().catch(() => undefined);
    state.audioContext = null;
  }

  if (state.audioObjectUrl) {
    URL.revokeObjectURL(state.audioObjectUrl);
    state.audioObjectUrl = null;
  }
}

function stopDemo(preserveError = false) {
  if (!preserveError) {
    clearError();
  }

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

  resetPlaybackState();
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
elements.sourceMic.addEventListener("change", renderControls);
elements.sourceFile.addEventListener("change", renderControls);
elements.audioFileInput.addEventListener("change", () => {
  clearError();
  renderControls();
});

if (!hasWebRTCSupport()) {
  elements.startButton.disabled = true;
  setText(elements.webrtcStatus, "unsupported");
  showError("This browser does not expose the WebRTC APIs required for the demo.");
}

renderControls();
loadConfig();
