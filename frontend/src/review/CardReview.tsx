// Teaching-card review (SPEC §11.1): render each card, edit fields inline, approve (bumps review.status, the backend
// writes the YAML) or flag. Both post to /api/review/ratings with item_type "card"; approve carries card_edits.
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { zoneDisplay } from '../api/labels';
import { RatingScale } from './RatingScale';
import type { Reviewer } from './reviewer';
import { approvalStatus, cardDraft, cardEdits, STATUS_TEXT, type CardField, type CardItem, type CardStatus } from './types';
import r from './Review.module.css';

const FIELDS: { f: CardField; label: string; list?: boolean; rows?: number; note?: string }[] = [
  { f: 'display_name', label: 'Display name' },
  { f: 'one_liner', label: 'One-liner', rows: 2 },
  { f: 'key_signs', label: 'Key signs', list: true, rows: 4 },
  { f: 'where_it_hides', label: 'Where it hides', list: true, rows: 3, note: 'Zone ids, patient side (e.g. right_lower_zone)' },
  { f: 'mimics', label: 'Mimics', list: true, rows: 3 },
  { f: 'commonly_confused_with', label: 'Commonly confused with', list: true, rows: 2, note: 'Label ids' },
  { f: 'search_tip', label: 'Search tip', rows: 2 },
  { f: 'radiopaedia_url', label: 'Radiopaedia link', note: 'Link only; leave blank if unsure' },
];

type Msg = { kind: 'ok' | 'err'; text: string } | null;

export function CardReview({ items, reviewer, onNeedReviewer }: { items: CardItem[]; reviewer: Reviewer; onNeedReviewer: () => void }) {
  const [sel, setSel] = useState(items[0]?.item_id ?? '');
  const [msg, setMsg] = useState<Msg>(null);
  const item = items.find((i) => i.item_id === sel) ?? items[0];
  return (
    <div className={r.cardLayout} data-testid="card-review">
      <nav className={r.cardList} aria-label="Teaching cards">
        {items.map((i) => (
          <button key={i.item_id} type="button" className={`${r.cardListItem} ${i.item_id === item.item_id ? r.cardListOn : ''}`}
            onClick={() => { setSel(i.item_id); setMsg(null); }} data-testid={`card-${i.item_id}`}>
            <span>{i.card.display_name}</span>
            <span className={r.statusText}>{STATUS_TEXT[i.card.review.status as CardStatus] ?? i.card.review.status}</span>
          </button>
        ))}
      </nav>
      {/* Keyed by content: a saved approval refetches the card and the editor starts fresh from the new file. */}
      <CardEditor key={`${item.item_id}:${JSON.stringify(item.card)}`} item={item} reviewer={reviewer} onNeedReviewer={onNeedReviewer} msg={msg} setMsg={setMsg} />
    </div>
  );
}

function CardEditor({ item, reviewer, onNeedReviewer, msg, setMsg }: {
  item: CardItem; reviewer: Reviewer; onNeedReviewer: () => void; msg: Msg; setMsg: (m: Msg) => void;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState(() => cardDraft(item.card));
  const [accuracy, setAccuracy] = useState<number | null>(null);
  const [teaching, setTeaching] = useState<number | null>(null);
  const [field, setField] = useState<'accuracy' | 'teaching'>('accuracy');
  const [comment, setComment] = useState('');
  const [safety, setSafety] = useState(false);

  const edits = useMemo(() => cardEdits(item.card, draft), [item.card, draft]);
  const nEdits = Object.keys(edits).length;
  const status = item.card.review.status as CardStatus;

  const rate = useMutation({
    mutationFn: (approve: boolean) => api.rate({
      reviewer: reviewer.name.trim(), role: reviewer.role, item_type: 'card', item_id: item.item_id,
      accuracy: accuracy!, teaching: teaching!, safety_flag: safety, comment: comment.trim() || null,
      card_edits: approve ? { ...edits, status: approvalStatus(reviewer.role, status) } : null,
    }),
    onSuccess: (_d, approve) => {
      setMsg({ kind: 'ok', text: approve ? `Approved as ${STATUS_TEXT[approvalStatus(reviewer.role, status)].toLowerCase()}${nEdits ? ` with ${nEdits} edited field${nEdits === 1 ? '' : 's'}` : ''}.` : 'Flagged. The card is unchanged; your note is in the export.' });
      void qc.invalidateQueries({ queryKey: ['review-items', 'card'] });
    },
    onError: (e) => setMsg({ kind: 'err', text: `Not saved: ${(e as Error).message.slice(0, 160)}` }),
  });

  const act = (approve: boolean) => {
    if (!reviewer.name.trim()) { setMsg({ kind: 'err', text: 'Enter your name and role above before reviewing.' }); onNeedReviewer(); return; }
    if (accuracy == null || teaching == null) { setMsg({ kind: 'err', text: 'Rate accuracy and teaching value first.' }); return; }
    if (!approve && !comment.trim()) { setMsg({ kind: 'err', text: 'Say what needs changing before flagging.' }); return; }
    setMsg(null);
    rate.mutate(approve);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (/^[1-5]$/.test(e.key)) {
        const v = Number(e.key);
        if (field === 'accuracy') { setAccuracy(v); setField('teaching'); } else setTeaching(v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [field]);

  return (
      <div className={r.cardBody}>
        <div className={r.cardHead}>
          <h2 className={r.cardTitle}>{item.card.display_name}</h2>
          <span className={r.muted}>{item.card.kind === 'focal' ? 'Focal finding' : 'Global pattern'} · {STATUS_TEXT[status]}</span>
        </div>
        {item.card.review.reviewer && <p className={r.pSmall}>Last reviewed by {item.card.review.reviewer}{item.card.review.date ? ` on ${item.card.review.date}` : ''}.</p>}
        {item.card.review.notes && <p className={r.pSmall}>Notes: {item.card.review.notes}</p>}

        {FIELDS.map(({ f, label, list, rows, note }) => {
          const changed = f in edits;
          return (
            <label key={f} className={`${r.cardField} ${changed ? r.changed : ''}`}>
              <span className={r.cardFieldLabel}>{label}{list && <span className={r.keyHint}> · one per line</span>}{changed && <span className={r.changedTag}>edited</span>}</span>
              {rows ? (
                <textarea className={r.textarea} rows={list ? Math.max(rows, draft[f].split("\n").length) : rows} value={draft[f]} onChange={(e) => setDraft({ ...draft, [f]: e.target.value })} data-testid={`field-${f}`} />
              ) : (
                <input className={r.input} value={draft[f]} onChange={(e) => setDraft({ ...draft, [f]: e.target.value })} data-testid={`field-${f}`} />
              )}
              {f === 'where_it_hides' && <span className={r.pSmall}>Reads as: {draft.where_it_hides.split('\n').filter(Boolean).map((z) => zoneDisplay(z.trim())).join(' · ')}</span>}
              {note && <span className={r.pSmall}>{note}</span>}
            </label>
          );
        })}
        {item.card.radiopaedia_url && <p className={r.pSmall}><a href={item.card.radiopaedia_url} target="_blank" rel="noreferrer">Open the Radiopaedia link</a> to check it.</p>}

        <div className={r.cardRate}>
          <RatingScale name="card-accuracy" label="Accuracy" value={accuracy} onChange={(v) => { setAccuracy(v); setField('teaching'); }}
            active={field === 'accuracy'} onFocus={() => setField('accuracy')} low="1 · wrong" high="5 · fully correct" />
          <RatingScale name="card-teaching" label="Teaching value" value={teaching} onChange={setTeaching}
            active={field === 'teaching'} onFocus={() => setField('teaching')} low="1 · useless" high="5 · excellent" />
          <label className={r.check}><input type="checkbox" checked={safety} onChange={(e) => setSafety(e.target.checked)} data-testid="card-safety" /> Safety concern</label>
          <label className={r.field}>
            <span>Note</span>
            <textarea className={r.textarea} rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Required when flagging." data-testid="card-comment" />
          </label>
          {msg && <p className={msg.kind === 'ok' ? r.ok : r.error} role="status" data-testid="card-msg">{msg.text}</p>}
          <div className={r.actions}>
            <button type="button" className={r.submit} onClick={() => act(true)} disabled={rate.isPending} data-testid="approve-card">
              Approve{nEdits ? ` with ${nEdits} edit${nEdits === 1 ? '' : 's'}` : ''}
            </button>
            <button type="button" className={r.secondary} onClick={() => act(false)} disabled={rate.isPending} data-testid="flag-card">Flag for changes</button>
            {nEdits > 0 && <button type="button" className={r.linkBtn} onClick={() => setDraft(cardDraft(item.card))}>Undo edits</button>}
          </div>
          <p className={r.pSmall}>Approving as {reviewer.role || 'a reviewer'} sets the card to “{STATUS_TEXT[approvalStatus(reviewer.role, status)]}” and writes your edits to the card file.</p>
        </div>
      </div>
  );
}
