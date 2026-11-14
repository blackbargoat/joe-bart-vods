import React from 'react';
import {
  AbsoluteFill,
  OffthreadVideo,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  continueRender,
  delayRender,
} from 'remotion';

export type Rect = [number, number, number, number]; // x, y, w, h in source pixels
export type Word = {start: number; end: number; text: string};
export type Zoom = {at: number; dur: number; scale: number; target?: 'cam' | 'game' | 'both'; shake?: boolean; hard?: boolean; origin?: string};

export type ShortProps = {
  clip: string; // file in public/
  sourceW: number;
  sourceH: number;
  durationSec: number;
  cam: Rect | null; // facecam box in the source; null = full-height single crop
  game: Rect | null; // gameplay box; null = whole frame
  split: number; // share of height for facecam
  words: Word[];
  captions: boolean;
  zooms: Zoom[];
  hook: string | null;
  title?: string | null; // title box on the cam/gameplay seam
  captionY?: number | null; // caption centre in px; default the seam
};

export const defaultProps: ShortProps = {
  clip: 'clip.mp4',
  sourceW: 1920,
  sourceH: 1080,
  durationSec: 5,
  cam: [40, 740, 480, 300],
  game: null,
  split: 0.37,
  words: [],
  captions: true,
  zooms: [],
  hook: null,
};

// Fit rect r to aspect tw:th by trimming around its centre (crop to fill, never squash).
const fill = (r: Rect, tw: number, th: number): Rect => {
  let [x, y, w, h] = r;
  const want = tw / th;
  if (w / h > want) {
    const nw = h * want;
    x += (w - nw) / 2;
    w = nw;
  } else {
    const nh = w / want;
    y += (h - nh) / 2;
    h = nh;
  }
  return [x, y, w, h];
};

const useZoom = (zooms: Zoom[], target: 'cam' | 'game') => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  let s = 1;
  let dx = 0;
  let dy = 0;
  let origin = '50% 45%';
  for (const z of zooms) {
    const tg = z.target ?? 'both';
    if (tg !== 'both' && tg !== target) continue;
    if (z.hard) {
      // instant punch-in for a whole section (cold open), optional shake
      if (frame >= Math.round(z.at * fps) && frame < Math.round((z.at + z.dur) * fps)) {
        s = Math.max(s, z.scale);
        if (z.origin) origin = z.origin;
        if (z.shake) {
          dx = Math.sin(frame * 2.1) * 9 + Math.sin(frame * 5.3) * 5;
          dy = Math.cos(frame * 1.7) * 7 + Math.sin(frame * 4.1) * 4;
        }
      }
      continue;
    }
    const startF = Math.round(z.at * fps);
    const endF = Math.round((z.at + z.dur) * fps);
    if (frame < startF - 1 || frame > endF + 12) continue;
    const pin = spring({frame: frame - startF, fps, config: {damping: 14, stiffness: 260, mass: 0.6}});
    const pout = spring({frame: frame - endF, fps, config: {damping: 20, stiffness: 180}});
    const v = 1 + (z.scale - 1) * (pin - pout);
    if (v > s && z.origin) origin = z.origin;
    s = Math.max(s, v);
  }
  return {s, dx, dy, origin};
};

const Panel: React.FC<{
  clip: string;
  sourceW: number;
  sourceH: number;
  rect: Rect;
  width: number;
  height: number;
  zoom: {s: number; dx: number; dy: number; origin: string};
  muted: boolean;
}> = ({clip, sourceW, sourceH, rect, width, height, zoom, muted}) => {
  const [x, y, w] = fill(rect, width, height);
  const k = width / w; // source px -> output px
  return (
    <div style={{width, height, overflow: 'hidden', position: 'relative'}}>
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width,
          height,
          transform: `translate(${zoom.dx}px, ${zoom.dy}px) scale(${zoom.s})`,
          transformOrigin: zoom.origin,
        }}
      >
        <OffthreadVideo
          src={staticFile(clip)}
          muted={muted}
          style={{
            position: 'absolute',
            width: sourceW * k,
            height: sourceH * k,
            left: -x * k,
            top: -y * k,
            maxWidth: 'none',
          }}
        />
      </div>
    </div>
  );
};

const fontHandle = (() => {
  if (typeof window === 'undefined') return null;
  const h = delayRender('font');
  const f = new FontFace('CapFont', `url(${staticFile('fonts/Montserrat-Black.ttf')})`);
  f.load()
    .then((ff) => {
      document.fonts.add(ff);
      continueRender(h);
    })
    .catch(() => continueRender(h));
  return h;
})();

const Captions: React.FC<{words: Word[]; y: number}> = ({words, y}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  // group into chunks of up to 3 words, breaking on punctuation or pauses
  const chunks: Word[][] = [];
  let cur: Word[] = [];
  words.forEach((w, i) => {
    const prev = words[i - 1];
    if (cur.length && (cur.length >= 3 || (prev && w.start - prev.end > 0.45))) {
      chunks.push(cur);
      cur = [];
    }
    cur.push(w);
    if (/[.!?,]$/.test(w.text)) {
      chunks.push(cur);
      cur = [];
    }
  });
  if (cur.length) chunks.push(cur);

  const idx = chunks.findIndex((c, i) => {
    const next = chunks[i + 1];
    const end = Math.min(next ? next[0].start : Infinity, c[c.length - 1].end + 0.6);
    return t >= c[0].start && t < end;
  });
  if (idx < 0) return null;
  const chunk = chunks[idx];
  const pop = spring({frame: frame - Math.round(chunk[0].start * fps), fps, config: {damping: 12, stiffness: 300, mass: 0.5}});
  const scale = interpolate(pop, [0, 1], [0.8, 1]);
  return (
    <div
      style={{
        position: 'absolute',
        top: y,
        left: 50,
        right: 50,
        transform: `translateY(-50%) scale(${scale})`,
        textAlign: 'center',
        fontFamily: 'CapFont, sans-serif',
        fontSize: 96,
        lineHeight: 1.05,
        color: 'white',
        textTransform: 'uppercase',
        WebkitTextStroke: '14px black',
        paintOrder: 'stroke fill',
        textShadow: '0 6px 0 rgba(0,0,0,0.55)',
      }}
    >
      {chunk.map((w, i) => {
        const active = t >= w.start && (i === chunk.length - 1 || t < chunk[i + 1].start);
        return (
          <span key={i} style={{color: active ? '#FFE600' : 'white'}}>
            {w.text.replace(/[,.]$/, '')}
            {i < chunk.length - 1 ? ' ' : ''}
          </span>
        );
      })}
    </div>
  );
};

export const Short: React.FC<ShortProps> = (p) => {
  const {width, height} = useVideoConfig();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const camZoom = useZoom(p.zooms, 'cam');
  const gameZoom = useZoom(p.zooms, 'game');
  const game: Rect = p.game ?? [0, 0, p.sourceW, p.sourceH];
  const topH = Math.round((height * p.split) / 2) * 2;
  const botH = height - topH;
  void fontHandle;
  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      {p.cam ? (
        <>
          <Panel clip={p.clip} sourceW={p.sourceW} sourceH={p.sourceH} rect={p.cam} width={width} height={topH} zoom={camZoom} muted={false} />
          <Panel clip={p.clip} sourceW={p.sourceW} sourceH={p.sourceH} rect={game} width={width} height={botH} zoom={gameZoom} muted />
        </>
      ) : (
        <Panel clip={p.clip} sourceW={p.sourceW} sourceH={p.sourceH} rect={game} width={width} height={height} zoom={camZoom} muted={false} />
      )}
      {p.title && (
        <div
          style={{
            position: 'absolute',
            top: p.cam ? topH : height * 0.12,
            left: 0,
            right: 0,
            display: 'flex',
            justifyContent: 'center',
            // sits just above the seam so the top of the gameplay (kill banners) stays visible
            transform: p.cam ? 'translateY(calc(-100% + 14px))' : 'translateY(-50%)',
          }}
        >
          <div
            style={{
              background: 'white',
              color: 'black',
              fontFamily: 'CapFont, "Noto Color Emoji", sans-serif',
              fontSize: 50,
              lineHeight: 1.15,
              padding: '18px 30px',
              borderRadius: 18,
              maxWidth: 900,
              textAlign: 'center',
              boxShadow: '0 6px 18px rgba(0,0,0,0.35)',
            }}
          >
            {p.title}
          </div>
        </div>
      )}
      {p.captions && p.words.length > 0 && (
        <Captions words={p.words} y={p.captionY ?? (p.cam ? topH : height * 0.62)} />
      )}
      {p.hook && frame < 2.5 * fps && (
        <div
          style={{
            position: 'absolute',
            top: 140,
            left: 60,
            right: 60,
            textAlign: 'center',
            fontFamily: 'CapFont, sans-serif',
            fontSize: 70,
            color: 'white',
            WebkitTextStroke: '12px black',
            paintOrder: 'stroke fill',
          }}
        >
          {p.hook}
        </div>
      )}
    </AbsoluteFill>
  );
};
