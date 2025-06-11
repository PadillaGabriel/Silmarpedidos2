// Sonido de aviso
const beep = new Audio('/static/beep.mp3');

// Elementos de vídeo y canvas
const videoEl  = document.createElement('video');
const canvasEl = document.createElement('canvas');
const ctx      = canvasEl.getContext('2d');

// Configuración del vídeo para inline y sin PiP
videoEl.autoplay                  = true;
videoEl.muted                     = true;
videoEl.playsInline               = true;
videoEl.disablePictureInPicture   = true;
videoEl.disableRemotePlayback     = true;
videoEl.setAttribute('playsinline','');
videoEl.setAttribute('webkit-playsinline','');
videoEl.style.cssText = `
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
`;

videoEl.style.boxSizing   = 'border-box';
videoEl.style.aspectRatio = '16/9';

// Ocultamos el canvas (solo lo usamos para captura)
canvasEl.style.display = 'none';

// Insertamos ambos en #reader
const container = document.getElementById('reader');
container.style.position = 'relative';
container.append(videoEl, canvasEl);

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

async function escanearFrame() {
  if (!videoEl.videoWidth) return;

  // Captura de frame
  canvasEl.width  = videoEl.videoWidth;
  canvasEl.height = videoEl.videoHeight;
  ctx.drawImage(videoEl, 0, 0);

  // Envío al servidor
  canvasEl.toBlob(async blob => {
    const form = new FormData();
    form.append('frame', blob, 'frame.jpg');
    console.log('enviando frame...', blob);

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
  // aviso visual sin cambiar tamaño
  videoEl.style.outline = '5px solid lime';
  setTimeout(() => videoEl.style.outline = '', 500);
  // …
}

      // aviso sonoro
      beep.play().catch(() => {});
      // llama a tu lógica de negocio
      escanear(json.data);
    }
  }, 'image/jpeg');
}

document.addEventListener('DOMContentLoaded', () => {
  iniciarCamara().catch(e => console.error('Cámara:', e));
  setInterval(escanearFrame, 800);

  document.getElementById('stop-btn').onclick = () => {
    videoEl.srcObject?.getTracks().forEach(t => t.stop());
  };
});
