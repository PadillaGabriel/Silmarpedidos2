<!-- Asegúrate de tener estos botones en tu HTML -->
<button id="start-btn">▶️ Iniciar escaneo</button>
<button id="stop-btn" disabled>■ Detener escaneo</button>
<div id="reader"></div>

<script>
// Sonido de aviso
const beep = new Audio('/static/beep.mp3');

// Elementos de vídeo y canvas
const videoEl  = document.createElement('video');
const canvasEl = document.createElement('canvas');
const ctx      = canvasEl.getContext('2d');

// Configuración del vídeo para inline y sin PiP
videoEl.autoplay                = true;
videoEl.muted                   = true;
videoEl.playsInline             = true;
videoEl.disablePictureInPicture = true;
videoEl.disableRemotePlayback   = true;
videoEl.setAttribute('playsinline','');
videoEl.setAttribute('webkit-playsinline','');
videoEl.style.cssText = `
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  box-sizing: border-box;
  aspect-ratio: 16/9;
`;

// Ocultamos el canvas (solo lo usamos para captura)
canvasEl.style.display = 'none';

// Insertamos ambos en #reader
const container = document.getElementById('reader');
container.style.position = 'relative';
container.append(videoEl, canvasEl);

let escanearInterval = null;

async function iniciarCamara() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'environment', width:{ideal:640}, height:{ideal:480} }
  });
  videoEl.srcObject = stream;
  await videoEl.play();
}

async function escanearFrame() {
  if (!videoEl.videoWidth) return;
  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);
  canvasEl.toBlob(async blob => {
    const form = new FormData();
    form.append('frame', blob, 'frame.jpg');
    try {
      const res = await fetch('/decode-qr', {
        method: 'POST',
        body: form,
        credentials: 'include'
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.data) {
        // aviso visual
        videoEl.style.outline = '5px solid lime';
        setTimeout(() => videoEl.style.outline = '', 500);
        // aviso sonoro
        beep.play().catch(() => {});
        // tu lógica de negocio
        escanear(json.data);
      }
    } catch (e) {
      console.warn('Error decode-qr:', e);
    }
  }, 'image/jpeg');
}

document.getElementById('start-btn').addEventListener('click', async () => {
  const startBtn = document.getElementById('start-btn');
  const stopBtn  = document.getElementById('stop-btn');
  startBtn.disabled = true;
  try {
    await iniciarCamara();
    escanearInterval = setInterval(escanearFrame, 800);
    stopBtn.disabled = false;
  } catch (e) {
    console.error('No pude arrancar cámara:', e);
    startBtn.disabled = false;
  }
});

document.getElementById('stop-btn').addEventListener('click', () => {
  const startBtn = document.getElementById('start-btn');
  const stopBtn  = document.getElementById('stop-btn');
  videoEl.srcObject?.getTracks().forEach(t => t.stop());
  clearInterval(escanearInterval);
  stopBtn.disabled = true;
  startBtn.disabled = false;
});
</script>
