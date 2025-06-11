// scanner.js

// Sonido de aviso
const beep = new Audio('/static/beep.mp3');

// Creamos los elementos de vídeo y canvas
const videoEl  = document.createElement('video');
const canvasEl = document.createElement('canvas');
const ctx      = canvasEl.getContext('2d');

// Ajustes para el vídeo (inline, sin PiP, ocupando todo el contenedor)
videoEl.autoplay                = true;
videoEl.muted                   = true;
videoEl.playsInline             = true;
videoEl.disablePictureInPicture = true;
videoEl.disableRemotePlayback   = true;
videoEl.setAttribute('playsinline', '');
videoEl.setAttribute('webkit-playsinline', '');
videoEl.style.cssText = `
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  box-sizing: border-box;
  aspect-ratio: 16/9;
`;

// Ocultamos el canvas; sólo lo usamos para capturar frames
canvasEl.style.display = 'none';

// Insertamos vídeo + canvas dentro de #reader
const container = document.getElementById('reader');
container.style.position = 'relative';
container.append(videoEl, canvasEl);

// Función que inicializa la cámara (busca cámara trasera si existe)
async function iniciarCamara() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const back = devices.find(d =>
    d.kind === 'videoinput' && /back|rear|environment/i.test(d.label)
  );
  const constraintVideo = back
    ? { deviceId: { exact: back.deviceId } }
    : { facingMode: 'environment' };

  const stream = await navigator.mediaDevices.getUserMedia({
    video: { ...constraintVideo, width: { ideal: 640 }, height: { ideal: 480 } }
  });
  videoEl.srcObject = stream;
  await videoEl.play();
}

// Función que captura un frame y lo envía al servidor para decodificar
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
      if (!res.ok) {
        console.warn('HTTP', res.status);
        return;
      }
      const json = await res.json();
      console.log('respuesta decode-qr:', json);

      if (json.data) {
        // aviso visual
        videoEl.style.outline = '5px solid lime';
        setTimeout(() => videoEl.style.outline = '', 500);

        // aviso sonoro
        beep.play().catch(() => {});

        // tu lógica con el dato decodificado
        escanear(json.data);
      }
    } catch (e) {
      console.error('Error al escanear frame:', e);
    }
  }, 'image/jpeg');
}

// Arrancamos todo al cargar la página
document.addEventListener('DOMContentLoaded', () => {
  // Botones de control
  const startBtn = document.getElementById('start-btn');
  const stopBtn  = document.getElementById('stop-btn');

  let intervalo;

  startBtn.onclick = () => {
    iniciarCamara().catch(e => console.error('Cámara:', e));
    intervalo = setInterval(escanearFrame, 800);
    startBtn.disabled = true;
    stopBtn.disabled  = false;
  };

  stopBtn.onclick = () => {
    clearInterval(intervalo);
    videoEl.srcObject?.getTracks().forEach(t => t.stop());
    startBtn.disabled = false;
    stopBtn.disabled  = true;
  };

  // Si quieres que arranque automáticamente en lugar de con botón, descomenta:
  // startBtn.click();
});
