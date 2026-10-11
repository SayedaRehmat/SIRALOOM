"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { firebaseAuth } from "../../../../lib/firebase";
import { useLanguage } from "../../../../lib/i18n";

const API_BASE = (process.env.NEXT_PUBLIC_SIRALOOM_API_BASE ?? "http://localhost:8000/api/v1").replace(/\/$/, "");

type Analysis = { analysis_id: string; status: string; analysis_type?: string; reference_build?: string; analysis_version?: number; created_at?: string };
type CaseRow = { case_id: string; case_identifier: string; status: string; created_at?: string; updated_at?: string; specimens?: Array<{ specimen_id: string }>; analyses?: Analysis[] };
type NotificationRow = { notification_id: string; notification_type: string; status: string; title: string; body: string; case_id?: string | null; analysis_id?: string | null; candidate_id?: string | null; metadata?: Record<string, unknown>; created_at?: string };
type CapacityRoot = { label: string; total_bytes?: number | null; used_bytes?: number | null; free_bytes?: number | null; writable?: boolean | null };
type Capacity = { status?: string; capacity_preflight_enabled?: boolean; max_artifact_upload_bytes?: number; reservation_supported?: boolean; roots?: CapacityRoot[]; issues?: Array<{ code: string; message: string; storage?: string }> };

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

function pretty(value?: string | null) {
  return String(value ?? "—").toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatBytes(value?: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toFixed(amount >= 100 ? 0 : amount >= 10 ? 1 : 2)} ${units[unit]}`;
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function statusTone(value?: string | null) {
  const status = String(value ?? "").toUpperCase();
  if (["SUCCEEDED", "FINAL", "APPROVED", "READ", "ACTIVE"].includes(status)) return "success";
  if (["BLOCKED", "FAILED", "REQUIRES_REVIEW", "UNREAD", "NEEDS_REVIEW"].includes(status)) return "danger";
  if (["RUNNING", "QUEUED", "IN_PROGRESS", "PENDING"].includes(status)) return "active";
  return "neutral";
}

export default function Dashboard() {
  const { t } = useLanguage();
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [notifications, setNotifications] = useState<NotificationRow[]>([]);
  const [capacity, setCapacity] = useState<Capacity | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [actionMessage, setActionMessage] = useState("");
  const [markingId, setMarkingId] = useState<string | null>(null);

  const load = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true); else setLoading(true);
    setErrors([]);
    const results = await Promise.allSettled([
      apiFetch("/cases"),
      apiFetch("/notifications"),
      apiFetch("/storage/capacity"),
    ]);
    const nextErrors: string[] = [];
    if (results[0].status === "fulfilled") setCases(Array.isArray(results[0].value) ? results[0].value : []);
    else nextErrors.push(`${t("dashboard.caseDataUnavailable")}: ${results[0].reason instanceof Error ? results[0].reason.message : "API error"}`);
    if (results[1].status === "fulfilled") setNotifications(Array.isArray(results[1].value) ? results[1].value : []);
    else nextErrors.push(`${t("dashboard.notificationDataUnavailable")}: ${results[1].reason instanceof Error ? results[1].reason.message : "API error"}`);
    if (results[2].status === "fulfilled") setCapacity(results[2].value && typeof results[2].value === "object" ? results[2].value : null);
    else setCapacity(null);
    setErrors(nextErrors);
    setLoading(false);
    setRefreshing(false);
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const markRead = async (notification: NotificationRow) => {
    setMarkingId(notification.notification_id);
    setActionMessage("");
    try {
      await apiFetch(`/notifications/${notification.notification_id}/read`, { method: "POST" });
      setNotifications(current => current.map(item => item.notification_id === notification.notification_id ? { ...item, status: "READ" } : item));
    } catch (e) {
      setActionMessage(e instanceof Error ? e.message : t("dashboard.actionFailed"));
    } finally {
      setMarkingId(null);
    }
  };

  const latestAnalysis = (item: CaseRow) => (item.analyses ?? [])[0] ?? null;
  const activeStatuses = ["CREATED", "QUEUED", "RUNNING", "BLOCKED", "REQUIRES_REVIEW", "IN_PROGRESS"];
  const attentionStatuses = ["BLOCKED", "REQUIRES_REVIEW", "FAILED", "NEEDS_REVIEW"];
  const activeAnalysisCount = cases.reduce((count, item) => count + (item.analyses ?? []).filter(analysis => activeStatuses.includes(String(analysis.status).toUpperCase())).length, 0);
  const attentionCount = cases.reduce((count, item) => count + (item.analyses ?? []).filter(analysis => attentionStatuses.includes(String(analysis.status).toUpperCase())).length, 0);
  const unreadCount = notifications.filter(item => String(item.status).toUpperCase() === "UNREAD").length;
  const recentCases = [...cases].sort((a, b) => new Date(b.updated_at ?? b.created_at ?? 0).getTime() - new Date(a.updated_at ?? a.created_at ?? 0).getTime()).slice(0, 8);

  const openNotification = (notification: NotificationRow) => {
    if (notification.case_id) {
      window.localStorage.setItem("siraloom.case_id", notification.case_id);
      if (notification.analysis_id) window.localStorage.setItem("siraloom.analysis_id", notification.analysis_id);
      return;
    }
    if (notification.analysis_id) window.localStorage.setItem("siraloom.analysis_id", notification.analysis_id);
  };

  if (loading) return <div className="operations-dashboard"><div className="empty"><strong>{t("session.checking")}</strong></div></div>;

  return (
    <main className="operations-dashboard">
      <header className="operations-heading">
        <div>
          <p className="eyebrow">{t("dashboard.eyebrow")}</p>
          <h1>{t("dashboard.title")}</h1>
          <p className="lead">{t("dashboard.lead")}</p>
        </div>
        <div className="operations-heading-actions">
          <span className="operations-updated">{t("dashboard.operationalView")}</span>
          <button className="secondary" type="button" onClick={() => void load(true)} disabled={refreshing}>{refreshing ? t("cases.refreshing") : t("cases.refresh")}</button>
        </div>
      </header>

      {errors.map((error, index) => <div className="notice error-notice" role="status" key={index}>{error}</div>)}
      {actionMessage && <div className="notice error-notice" role="status">{actionMessage}</div>}

      <section className="operations-metrics" aria-label={t("dashboard.operationalView")}>
        <article><span>{t("dashboard.totalCases")}</span><strong>{cases.length}</strong><small>{t("dashboard.totalCasesHint")}</small></article>
        <article><span>{t("dashboard.activeAnalyses")}</span><strong>{activeAnalysisCount}</strong><small>{t("dashboard.activeAnalysesHint")}</small></article>
        <article><span>{t("dashboard.needsAttention")}</span><strong>{attentionCount}</strong><small>{t("dashboard.needsAttentionHint")}</small></article>
        <article><span>{t("dashboard.unreadNotifications")}</span><strong>{unreadCount}</strong><small>{t("dashboard.unreadNotificationsHint")}</small></article>
      </section>

      <div className="operations-main-grid">
        <section className="panel operations-worklist">
          <div className="panel-head">
            <div><p className="eyebrow">{t("dashboard.worklist")}</p><h2>{t("dashboard.recentCases")}</h2><p className="muted">{t("dashboard.recentCasesHint")}</p></div>
            <Link className="secondary link-button" href="/app/cases">{t("dashboard.viewAllCases")}</Link>
          </div>
          {!recentCases.length ? <div className="empty small"><strong>{t("cases.none")}</strong><p>{t("cases.createHelp")}</p><Link className="primary link-button" href="/app/cases">{t("dashboard.createCase")}</Link></div> : <div className="operations-case-list">
            {recentCases.map(item => {
              const analysis = latestAnalysis(item);
              return <article key={item.case_id}>
                <div className="operations-case-identity">
                  <strong>{item.case_identifier}</strong>
                  <small>{pretty(item.status)} · {(item.specimens ?? []).length} {t("cases.specimenCount")}</small>
                  <small>{t("dashboard.lastUpdated")}: {formatDate(item.updated_at ?? item.created_at)}</small>
                </div>
                <div className="operations-case-analysis">
                  {analysis ? <><span className={`badge ${statusTone(analysis.status)}`}>{pretty(analysis.status)}</span><small>{analysis.reference_build ?? "—"} · v{analysis.analysis_version ?? 1}</small></> : <span className="muted">{t("cases.noAnalysis")}</span>}
                </div>
                <Link className="operations-open-link" href={`/app/cases/${item.case_id}`}>{t("cases.openDossier")}</Link>
              </article>;
            })}
          </div>}
        </section>

        <section className="panel operations-notifications">
          <div className="panel-head">
            <div><p className="eyebrow">{t("dashboard.attention")}</p><h2>{t("dashboard.notifications")}</h2></div>
            <span className="badge neutral">{unreadCount} {t("dashboard.unread")}</span>
          </div>
          {!notifications.length ? <div className="empty small"><strong>{t("dashboard.noNotifications")}</strong></div> : <div className="operations-notification-list">
            {notifications.slice(0, 8).map(notification => {
              const destination = notification.case_id ? `/app/cases/${notification.case_id}` : notification.analysis_id ? "/app/workspace" : "/app/resources";
              return <article key={notification.notification_id}>
                <div className="operations-notification-head">
                  <strong>{notification.title}</strong>
                  <span className={`badge ${statusTone(notification.status)}`}>{pretty(notification.status)}</span>
                </div>
                <p>{notification.body}</p>
                <small>{pretty(notification.notification_type)} · {formatDate(notification.created_at)}</small>
                <div className="operations-notification-actions">
                  <Link className="operations-open-link" href={destination} onClick={() => openNotification(notification)}>{t("dashboard.openNotification")}</Link>
                  {String(notification.status).toUpperCase() === "UNREAD" && <button className="text-button" type="button" disabled={markingId === notification.notification_id} onClick={() => void markRead(notification)}>{markingId === notification.notification_id ? t("cases.refreshing") : t("dashboard.markRead")}</button>}
                </div>
              </article>;
            })}
          </div>}
          {notifications.length > 8 && <p className="muted">{t("dashboard.notificationsPreviewLimit")}</p>}
        </section>
      </div>

      <section className="panel operations-capacity">
        <div className="panel-head">
          <div><p className="eyebrow">{t("dashboard.infrastructure")}</p><h2>{t("resources.storageCapacity")}</h2></div>
          <Link className="secondary link-button" href="/app/resources">{t("nav.resources")}</Link>
        </div>
        {!capacity ? <div className="empty small"><strong>{t("dashboard.capacityUnavailable")}</strong><p>{t("dashboard.capacityUnavailableHint")}</p></div> : <>
          <div className="operations-capacity-summary">
            <span>{capacity.capacity_preflight_enabled ? t("resources.capacityPreflightEnabled") : t("resources.capacityPreflightDisabled")}</span>
            <span>{t("resources.uploadLimit")}: <strong>{formatBytes(capacity.max_artifact_upload_bytes)}</strong></span>
            {capacity.reservation_supported === false && <span>{t("workspace.capacityReservationNotProvided")}</span>}
          </div>
          <div className="operations-capacity-roots">
            {(capacity.roots ?? []).map(root => <article key={root.label}>
              <strong>{pretty(root.label)}</strong>
              <span>{t("resources.freeStorage")}</span><b>{formatBytes(root.free_bytes)}</b>
              <span>{t("resources.totalStorage")}</span><b>{formatBytes(root.total_bytes)}</b>
              {typeof root.writable === "boolean" && <small>{root.writable ? t("resources.storageWritable") : t("dashboard.storageNotWritable")}</small>}
            </article>)}
          </div>
          {(capacity.issues ?? []).map((issue, index) => <div className="notice error-notice" key={index}>{issue.storage ? `${issue.storage}: ` : ""}{issue.code}: {issue.message}</div>)}
        </>}
      </section>
    </main>
  );
}
