// scanner.js

// Sonido de aviso
const beep = new Audio('/static/beep.mp3');

// Elementos de vídeo y canvas
const videoEl  = document.createElement('video');
const canvasEl = document.createElement('canvas');
const ctx      = canvasEl.getContext('2d');

// Flag para controlar cuándo escanear
let scanning = false;

// Estilos y atributos del vídeo
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

// Insertamos en #reader
const container = document.getElementById('reader');
container.style.position = 'relative';
container.append(videoEl, canvasEl);

// Inicializa la cámara trasera
async function iniciarCamara() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const back = devices.find(d =>
    d.kind === 'videoinput' && /back|rear|environment/i.test(d.label)
  );
  const constraintVideo = back
    ? { deviceId: { exact: back.deviceId } }
    : { facingMode: 'environment' };

  const stream = await navigator.mediaDevices.getUserMedia({
    video: { ...constraintVideo, width:{ideal:640}, height:{ideal:480} }
  });
  videoEl.srcObject = stream;
  await videoEl.play();
}

// Envía un frame al servidor para decodificar QR
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
        // marco visual
        videoEl.style.outline = '5px solid lime';
        setTimeout(() => videoEl.style.outline = '', 500);

        // sonido
        beep.play().catch(() => {});

        // tu lógica con el dato
        escanear(json.data);
        // y desactivo scanning para no repetir
        scanning = false;
      }
    } catch (e) {
      document.getElementById('error-msg').textContent = 'QR no detectado';
    }
  }, 'image/jpeg');
}

document.addEventListener('DOMContentLoaded', () => {
  iniciarCamara().catch(e => {
    console.error('Cámara:', e);
    document.getElementById('error-msg').textContent = 'No se pudo acceder a la cámara';
  });

  // cada 800 ms solo si scanning === true
  setInterval(() => {
    if (scanning) escanearFrame();
  }, 800);

  // Botón para empezar a escanear
  document.getElementById('scan-btn').onclick = () => {
    document.getElementById('error-msg').textContent = '';
    scanning = true;
  };

  // Botón para detener cámara
  document.getElementById('stop-btn').onclick = () => {
    scanning = false;
    videoEl.srcObject?.getTracks().forEach(t => t.stop());
  };

  // (añade aquí tus listeners de input-escanear y btn-manual)
});
