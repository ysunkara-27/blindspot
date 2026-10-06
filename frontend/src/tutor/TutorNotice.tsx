// The tutor status banner: a calm, amber-outlined line at the top of the reading-room rail and on the start page,
// shown only while the AI tutor is not live. Health is polled every 60 s; a debrief that ends in an error asks for a
// fresh poll (DebriefPanel). Reviewers (server-set review cookie) also see today's spend when the server reports it.
import { useHealth, useIsReviewer } from './health';
import { bannerText, spendText, tutorStatus } from './status';
import s from './TutorNotice.module.css';

export function TutorNotice({ className }: { className?: string }) {
  const health = useHealth();
  const reviewer = useIsReviewer();
  const t = tutorStatus(health.data);
  const text = bannerText(t);
  if (!text) return null;
  const spend = reviewer ? spendText(t) : null;
  return (
    <div className={`${s.notice} ${className ?? ''}`} role="status" data-testid="tutor-notice" data-mode={t?.mode}>
      <p className={s.text}>{text}</p>
      {spend && <p className={s.spend} data-testid="tutor-spend">{spend}</p>}
    </div>
  );
}
