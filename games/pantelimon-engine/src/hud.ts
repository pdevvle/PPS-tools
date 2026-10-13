// The on-screen text: date and time, where you are, who you are looking at.
import type { Agent } from './crowd/crowd';

const ROOMS: Record<string, string> = {
  living: 'sufragerie', bedroom: 'dormitor', kids: 'camera copiilor', kitchen: 'bucătărie', bath: 'baie', hall: 'hol', storage: 'cămară',
  stair: 'casa scării', lobby: 'intrare', shop: 'magazin', classroom: 'clasă', corridor: 'coridor', office: 'birou', workshop: 'atelier', nave: 'naos', garage: 'garaj', porch: 'verandă',
};
export class Hud {
  private el = {
    clock: document.getElementById('clock')!, place: document.getElementById('place')!, who: document.getElementById('who')!,
    stats: document.getElementById('stats')!, status: document.getElementById('status')!, help: document.getElementById('help')!, toast: document.getElementById('toast')!,
  };
  private toastT = 0;
  status(s: string) { this.el.status.textContent = s; this.el.status.hidden = !s; }
  toast(s: string) { this.el.toast.textContent = s; this.el.toast.hidden = false; clearTimeout(this.toastT); this.toastT = window.setTimeout(() => (this.el.toast.hidden = true), 2200); }
  toggleHelp() { this.el.help.hidden = !this.el.help.hidden; }
  locked(on: boolean) { if (on) this.el.help.hidden = true; }
  update(s: { hours: number; weather: string; place: string; room: string; who: Agent | null; stats: string }) {
    const h = Math.floor(s.hours), m = Math.floor((s.hours - h) * 60);
    this.el.clock.textContent = `Vineri, 22 decembrie 1989 · ${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')} · ${s.weather}`;
    this.el.place.textContent = s.room ? `${s.place} — ${ROOMS[s.room] || s.room}` : s.place;
    if (s.who) { this.el.who.hidden = false; this.el.who.innerHTML = `<b>${s.who.name}</b><br>${s.who.info}<br><i>${s.who.what}</i>`; }
    else this.el.who.hidden = true;
    this.el.stats.textContent = s.stats;
    this.el.stats.hidden = !s.stats;
  }
}
