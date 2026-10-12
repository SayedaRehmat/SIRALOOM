"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";
import { useLanguage } from "../../../../lib/i18n";

const API_BASE = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

type NotificationItem = {
  notification_id: string;
  notification_type: string;
  status: string;
  title: string;
  body: string;
  case_id?: string | null;
  analysis_id?: string | null;
  candidate_id?: string | null;
  metadata?: Record<string, unknown>;
  created_at?: string;
  read_at?: string | null;
};

type Candidate = {
  candidate_id: string;
  case_id: string;
  parent_analysis_id: string;
  child_analysis_id?: string | null;
  trigger_type: string;
  earliest_affected_step?: string | null;
  reason: string;
  status: string;
  created_at?: string;
  acted_at?: string | null;
};

type Capacity = {
  available_bytes?: number;
  total_bytes?: number;
  used_bytes?: number;
  free_bytes?: number;
  path?: string;
  status?: string;
  [key: string]: unknown;
};

type StorageProfile = {
  storage_profile_id: string;
  name: string;
  version: number;
  backend_type: string;
  storage_key: string;
  status: string;
};

async function apiFetch(path: string, init?: RequestInit) {
  const token = await firebaseAuth?.currentUser?.getIdToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(init?.headers ?? {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  const text = await response.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) throw new Error(body?.detail ? String(body.detail) : `HTTP ${response.status}`);
  return body;
}

function bytes(value?: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let n = value; let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n.toFixed(n >= 100 ? 0 : n >= 10 ? 1 : 2)} ${units[i]}`;
}

function pretty(value?: string | null) {
  return value ? value.toLowerCase().replaceAll("_", " ").replace(/\\b\\w/g, c => c.toUpperCase()) : "—";
}

export default function OperationsPage() {
  const { language } = useLanguage();
  const copy = language === "ar" ? {
    eyebrow: "عمليات المختبر", title: "التنبيهات وإعادة التحليل والسعة", lead: "نقطة تشغيل واحدة للإجراءات التي تتطلب انتباهاً من المختبر.",
    refresh: "تحديث", notifications: "التنبيهات", reanalysis: "مرشحو إعادة التحليل", capacity: "سعة التخزين", storage: "ملفات التخزين",
    unread: "غير مقروء", markRead: "تحديد كمقروء", openCase: "فتح الحالة", execute: "تنفيذ إعادة التحليل", pending: "معلّق", noNotifications: "لا توجد تنبيهات.", noCandidates: "لا توجد حالات مرشحة لإعادة التحليل.",
    capacityNote: "تعرض هذه القيم القياس الفعلي الذي يقدمه نشر المختبر؛ لا يتم استنتاج السعة من حد رفع الملفات.", active: "نشط", activate: "تفعيل", activeProfile: "ملف نشط", noProfiles: "لا توجد ملفات تخزين مسجلة.",
    queued: "تمت جدولة إعادة التحليل", failed: "تعذر تنفيذ الإجراء", source: "المصدر", affected: "أقدم مرحلة متأثرة", reason: "السبب", status: "الحالة", version: "الإصدار"
  } : {
    eyebrow: "LABORATORY OPERATIONS", title: "Notifications, reanalysis and capacity", lead: "One operational view for changes that require laboratory attention or action.",
    refresh: "Refresh", notifications: "Notifications", reanalysis: "Reanalysis candidates", capacity: "Storage capacity", storage: "Storage profiles",
    unread: "Unread", markRead: "Mark read", openCase: "Open case", execute: "Execute reanalysis", pending: "Pending", noNotifications: "No notifications.", noCandidates: "No reanalysis candidates are waiting.",
    capacityNote: "These figures come from the deployment capacity probe. SIRALOOM does not infer laboratory capacity from an upload-size setting.", active: "Active", activate: "Activate", activeProfile: "Active profile", noProfiles: "No storage profiles are registered.",
    queued: "Reanalysis dispatched", failed: "Action failed", source: "Source", affected: "Earliest affected stage", reason: "Reason", status: "Status", version: "Version"
  };

  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [capacity, setCapacity] = useState<Capacity | null>(null);
  const [profiles, setProfiles] = useState<StorageProfile[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setBusy(true); setMessage("");
    try {
      const [n, c, cap, p] = await Promise.all([
        apiFetch("/notifications"),
        apiFetch("/reanalysis/candidates"),
        apiFetch("/storage/capacity"),
        apiFetch("/storage/profiles"),
      ]);
      setNotifications(Array.isArray(n) ? n : []);
      setCandidates(Array.isArray(c) ? c : []);
      setCapacity(cap ?? null);
      setProfiles(Array.isArray(p) ? p : []);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load laboratory operations.");
    } finally { setBusy(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const unreadCount = useMemo(() => notifications.filter(n => n.status !== "READ").length, [notifications]);

  async function markRead(id: string) {
    try { await apiFetch(`/notifications/${encodeURIComponent(id)}/read`, { method: "POST" }); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Unable to update notification."); }
  }

  async function execute(candidate: Candidate) {
    setBusy(true); setMessage("");
    try {
      await apiFetch(`/reanalysis/candidates/${encodeURIComponent(candidate.candidate_id)}/execute`, { method: "POST" });
      setMessage(copy.queued); await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : copy.failed); }
    finally { setBusy(false); }
  }

  async function activate(profileId: string) {
    setBusy(true); setMessage("");
    try { await apiFetch(`/storage/profiles/${encodeURIComponent(profileId)}/activate`, { method: "POST" }); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : copy.failed); }
    finally { setBusy(false); }
  }

  return (
    <div className="lab-page">
      <header className="page-header">
        <div><p className="eyebrow">{copy.eyebrow}</p><h1>{copy.title}</h1><p className="lead">{copy.lead}</p></div>
        <button className="button secondary" onClick={() => void load()} disabled={busy}>{copy.refresh}</button>
      </header>
      {message && <div className="notice" role="status">{message}</div>}

      <section className="panel">
        <div className="section-heading"><div><h2>{copy.notifications}</h2><p className="muted">{unreadCount} {copy.unread}</p></div></div>
        {notifications.length === 0 ? <p className="muted">{copy.noNotifications}</p> : <div className="operation-list">
          {notifications.map(item => <article className={`operation-row ${item.status !== "READ" ? "is-unread" : ""}`} key={item.notification_id}>
            <div className="operation-main"><div className="operation-title"><strong>{item.title}</strong><span className="badge neutral">{pretty(item.notification_type)}</span></div><p>{item.body}</p><small>{item.created_at ? new Date(item.created_at).toLocaleString() : ""}</small></div>
            <div className="operation-actions">{item.case_id && <Link className="text-link" href={`/app/workspace?case=${encodeURIComponent(item.case_id)}`}>{copy.openCase}</Link>}{item.status !== "READ" && <button className="text-button" onClick={() => void markRead(item.notification_id)}>{copy.markRead}</button>}</div>
          </article>)}
        </div>}
      </section>

      <section className="panel">
        <div className="section-heading"><div><h2>{copy.reanalysis}</h2><p className="muted">{copy.lead}</p></div></div>
        {candidates.length === 0 ? <p className="muted">{copy.noCandidates}</p> : <div className="operation-list">
          {candidates.map(candidate => <article className="operation-row" key={candidate.candidate_id}>
            <div className="operation-main"><div className="operation-title"><strong>{candidate.case_id}</strong><span className="badge neutral">{pretty(candidate.trigger_type)}</span><span className="badge active">{pretty(candidate.status)}</span></div><p>{candidate.reason}</p><div className="metadata-line"><span>{copy.affected}: <b>{pretty(candidate.earliest_affected_step)}</b></span><span>{copy.source}: <b>{candidate.parent_analysis_id}</b></span></div></div>
            <div className="operation-actions">{candidate.status === "PENDING" || candidate.status === "STARTED" ? <button className="button" disabled={busy} onClick={() => void execute(candidate)}>{copy.execute}</button> : <span className="muted">{pretty(candidate.status)}</span>}</div>
          </article>)}
        </div>}
      </section>

      <div className="operations-grid">
        <section className="panel">
          <div className="section-heading"><div><h2>{copy.capacity}</h2><p className="muted">{copy.capacityNote}</p></div></div>
          {capacity ? <div className="capacity-metrics"><div><small>Free</small><strong>{bytes(Number(capacity.free_bytes ?? capacity.available_bytes))}</strong></div><div><small>Used</small><strong>{bytes(Number(capacity.used_bytes))}</strong></div><div><small>Total</small><strong>{bytes(Number(capacity.total_bytes))}</strong></div><div><small>Status</small><strong>{pretty(String(capacity.status ?? "UNKNOWN"))}</strong></div></div> : <p className="muted">—</p>}
          {capacity?.path && <p className="metadata-line">Path: <b>{String(capacity.path)}</b></p>}
        </section>

        <section className="panel">
          <div className="section-heading"><div><h2>{copy.storage}</h2><p className="muted">{copy.activeProfile}: {profiles.find(p => p.status === "ACTIVE")?.name ?? "—"}</p></div></div>
          {profiles.length === 0 ? <p className="muted">{copy.noProfiles}</p> : <div className="operation-list compact">{profiles.map(profile => <div className="operation-row" key={profile.storage_profile_id}><div className="operation-main"><strong>{profile.name}</strong><small>{profile.backend_type} · {profile.storage_key}</small><span className="metadata-line">{copy.version}: {profile.version}</span></div><div className="operation-actions">{profile.status === "ACTIVE" ? <span className="badge success">{copy.active}</span> : <button className="text-button" disabled={busy} onClick={() => void activate(profile.storage_profile_id)}>{copy.activate}</button>}</div></div>)}</div>}
        </section>
      </div>
    </div>
  );
}
