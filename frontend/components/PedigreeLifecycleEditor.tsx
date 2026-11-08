"use client";

import { useState } from "react";
import { useLanguage } from "../lib/i18n";

type ApiFetch = (path: string, init?: RequestInit) => Promise<any>;
type Specimen = { specimen_id: string; specimen_identifier: string; specimen_type: string };
type Member = {
  id: string;
  member_identifier: string;
  relationship_to_proband?: string | null;
  sex?: string | null;
  affected_status: "AFFECTED" | "UNAFFECTED" | "UNKNOWN";
  is_proband: boolean;
  sampled: boolean;
  specimen_id?: string | null;
  status?: string;
  revision_version?: number;
  revision_history?: Array<Record<string, any>>;
};
type Relationship = {
  id: string;
  parent_member_id: string;
  child_member_id: string;
  relationship_type: string;
  metadata?: Record<string, unknown>;
  status?: string;
  revision_version?: number;
  revision_history?: Array<Record<string, any>>;
};
type Props = {
  caseId: string;
  members: Member[];
  relationships: Relationship[];
  specimens: Specimen[];
  canWrite: boolean;
  apiFetch: ApiFetch;
  onChanged: () => Promise<void>;
};

export default function PedigreeLifecycleEditor({
  caseId, members, relationships, specimens, canWrite, apiFetch, onChanged,
}: Props) {
  const { t } = useLanguage();
  const [memberDraft, setMemberDraft] = useState<Member | null>(null);
  const [memberReason, setMemberReason] = useState("");
  const [relationshipDraft, setRelationshipDraft] = useState<Relationship | null>(null);
  const [relationshipReason, setRelationshipReason] = useState("");
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const beginMemberEdit = (member: Member) => {
    setMemberDraft({ ...member });
    setMemberReason("");
    setError("");
    setNotice("");
  };

  const saveMember = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!memberDraft || !memberReason.trim()) return;
    setBusyId(memberDraft.id);
    setError("");
    setNotice("");
    try {
      await apiFetch(`/cases/${caseId}/pedigree/members/${memberDraft.id}/revisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision_type: "CORRECTED",
          reason: memberReason.trim(),
          relationship_to_proband: memberDraft.relationship_to_proband || null,
          sex: memberDraft.sex || null,
          affected_status: memberDraft.affected_status,
          is_proband: memberDraft.is_proband,
          sampled: memberDraft.sampled || Boolean(memberDraft.specimen_id),
          specimen_id: memberDraft.specimen_id || null,
        }),
      });
      setMemberDraft(null);
      setMemberReason("");
      await onChanged();
      setNotice(t("review.saveMemberCorrection"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to correct pedigree member.");
    } finally {
      setBusyId("");
    }
  };

  const retractMember = async (member: Member) => {
    if (!memberReason.trim()) {
      setError(t("review.memberCorrectionReason"));
      return;
    }
    setBusyId(member.id);
    setError("");
    setNotice("");
    try {
      await apiFetch(`/cases/${caseId}/pedigree/members/${member.id}/revisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision_type: "RETRACTED", reason: memberReason.trim() }),
      });
      setMemberDraft(null);
      setMemberReason("");
      await onChanged();
      setNotice(t("review.retractMember"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to retract pedigree member.");
    } finally {
      setBusyId("");
    }
  };

  const saveRelationship = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!relationshipDraft || !relationshipReason.trim()) return;
    setBusyId(relationshipDraft.id);
    setError("");
    setNotice("");
    try {
      await apiFetch(`/cases/${caseId}/pedigree/relationships/${relationshipDraft.id}/revisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision_type: "CORRECTED",
          reason: relationshipReason.trim(),
          relationship_type: relationshipDraft.relationship_type,
        }),
      });
      setRelationshipDraft(null);
      setRelationshipReason("");
      await onChanged();
      setNotice(t("review.saveRelationshipCorrection"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to correct pedigree relationship.");
    } finally {
      setBusyId("");
    }
  };

  const retractRelationship = async (relationship: Relationship) => {
    if (!relationshipReason.trim()) {
      setError(t("review.relationshipCorrectionReason"));
      return;
    }
    setBusyId(relationship.id);
    setError("");
    setNotice("");
    try {
      await apiFetch(`/cases/${caseId}/pedigree/relationships/${relationship.id}/revisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision_type: "RETRACTED", reason: relationshipReason.trim() }),
      });
      setRelationshipDraft(null);
      setRelationshipReason("");
      await onChanged();
      setNotice(t("review.retractRelationship"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to retract pedigree relationship.");
    } finally {
      setBusyId("");
    }
  };

  const memberLabel = (id: string) =>
    members.find((member) => member.id === id)?.member_identifier ?? id;

  return (
    <section className="clinical-section" aria-labelledby="pedigree-editor-heading">
      <div className="clinical-card">
        <h3 id="pedigree-editor-heading">{t("review.pedigreeEditor")}</h3>
        <p className="quiet">{t("review.pedigreeEditorHelp")}</p>
        {error && <p role="alert" className="danger-text">{error}</p>}
        {notice && <p role="status" aria-live="polite">{notice}</p>}
        <div className="pedigree-grid">
          <section className="clinical-card" aria-labelledby="pedigree-members-heading">
            <h4 id="pedigree-members-heading">{t("review.family")}</h4>
            {members.length === 0 ? <p className="quiet">{t("review.familyNone")}</p> : (
              <ul className="pedigree-member-list">
                {members.map((member) => (
                  <li className="pedigree-member" key={member.id}>
                    <div>
                      <strong>{member.member_identifier}{member.is_proband ? " · Proband" : ""}</strong>
                      <small>
                        {member.relationship_to_proband || "relative"} · {member.affected_status}
                        {member.sex ? ` · ${member.sex}` : ""}
                        {member.sampled ? " · sampled" : ""}
                        {member.specimen_id ? ` · ${specimens.find((item) => item.specimen_id === member.specimen_id)?.specimen_identifier ?? "linked specimen"}` : ""}
                      </small>
                      <details>
                        <summary>{t("review.revisionHistory")} ({Math.max(0, (member.revision_history?.length ?? 1) - 1)})</summary>
                        {(member.revision_history ?? []).length > 1 ? (
                          <ol>
                            {(member.revision_history ?? []).map((revision) => (
                              <li key={String(revision.id)}>
                                <strong>{revision.version === 1 ? t("review.originalRecord") : `${t("review.revisionVersion")} ${revision.version}`}</strong>
                                {revision.reason && <p>{t("review.revisionReason")}: {revision.reason}</p>}
                                {revision.created_at && <small>{t("review.recordedAt")}: {new Date(revision.created_at).toLocaleString()}</small>}
                              </li>
                            ))}
                          </ol>
                        ) : <p className="quiet">{t("review.noRevisionHistory")}</p>}
                      </details>
                    </div>
                    {canWrite && (
                      <button type="button" className="secondary" onClick={() => beginMemberEdit(member)}>
                        {t("review.editMember")}
                      </button>
                    )}
                    {memberDraft?.id === member.id && (
                      <form onSubmit={saveMember} className="clinical-card">
                        <fieldset disabled={busyId === member.id}>
                          <legend>{t("review.editMember")}: {member.member_identifier}</legend>
                          <label>
                            {t("review.memberAffectedStatus")}
                            <select value={memberDraft.affected_status} onChange={(event) => setMemberDraft({ ...memberDraft, affected_status: event.target.value as Member["affected_status"] })}>
                              <option value="AFFECTED">AFFECTED</option>
                              <option value="UNAFFECTED">UNAFFECTED</option>
                              <option value="UNKNOWN">UNKNOWN</option>
                            </select>
                          </label>
                          <label>
                            {t("review.memberSex")}
                            <select value={memberDraft.sex ?? ""} onChange={(event) => setMemberDraft({ ...memberDraft, sex: event.target.value || null })}>
                              <option value="">UNKNOWN / NOT RECORDED</option>
                              <option value="MALE">MALE</option>
                              <option value="FEMALE">FEMALE</option>
                              <option value="UNKNOWN">UNKNOWN</option>
                            </select>
                          </label>
                          <label>
                            Relationship to proband
                            <input value={memberDraft.relationship_to_proband ?? ""} onChange={(event) => setMemberDraft({ ...memberDraft, relationship_to_proband: event.target.value || null })} maxLength={100}/>
                          </label>
                          <label>
                            {t("review.memberSpecimen")}
                            <select value={memberDraft.specimen_id ?? ""} onChange={(event) => setMemberDraft({ ...memberDraft, specimen_id: event.target.value || null, sampled: Boolean(event.target.value) || memberDraft.sampled })}>
                              <option value="">No linked specimen</option>
                              {specimens.map((specimen) => <option key={specimen.specimen_id} value={specimen.specimen_id}>{specimen.specimen_identifier} · {specimen.specimen_type}</option>)}
                            </select>
                          </label>
                          <label>
                            <input type="checkbox" checked={memberDraft.is_proband} onChange={(event) => setMemberDraft({ ...memberDraft, is_proband: event.target.checked })}/>
                            {t("review.memberProband")}
                          </label>
                          <label>
                            <input type="checkbox" checked={memberDraft.sampled} onChange={(event) => setMemberDraft({ ...memberDraft, sampled: event.target.checked })}/>
                            {t("review.memberSampled")}
                          </label>
                          <label>
                            {t("review.memberCorrectionReason")}
                            <textarea required value={memberReason} onChange={(event) => setMemberReason(event.target.value)} minLength={1} maxLength={5000} rows={3}/>
                          </label>
                          <button type="submit" className="primary" disabled={!memberReason.trim() || busyId === member.id}>{t("review.saveMemberCorrection")}</button>
                          <button type="button" className="secondary" onClick={() => void retractMember(member)} disabled={!memberReason.trim() || busyId === member.id}>{t("review.retractMember")}</button>
                          <button type="button" className="ghost" onClick={() => { setMemberDraft(null); setMemberReason(""); }}>{t("review.cancelEdit")}</button>
                        </fieldset>
                      </form>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="clinical-card" aria-labelledby="pedigree-relationships-heading">
            <h4 id="pedigree-relationships-heading">{t("review.parentChild")}</h4>
            {relationships.length === 0 ? <p className="quiet">{t("review.relationshipNone")}</p> : (
              <ul className="relationship-list">
                {relationships.map((relationship) => (
                  <li key={relationship.id} className="clinical-card">
                    <strong>{memberLabel(relationship.parent_member_id)} → {memberLabel(relationship.child_member_id)}</strong>
                    <small>{relationship.relationship_type}</small>
                    <details>
                      <summary>{t("review.revisionHistory")} ({Math.max(0, (relationship.revision_history?.length ?? 1) - 1)})</summary>
                      {(relationship.revision_history ?? []).length > 1 ? (
                        <ol>
                          {(relationship.revision_history ?? []).map((revision) => (
                            <li key={String(revision.id)}>
                              <strong>{revision.version === 1 ? t("review.originalRecord") : `${t("review.revisionVersion")} ${revision.version}`}</strong>
                              {revision.reason && <p>{t("review.revisionReason")}: {revision.reason}</p>}
                              {revision.created_at && <small>{t("review.recordedAt")}: {new Date(revision.created_at).toLocaleString()}</small>}
                            </li>
                          ))}
                        </ol>
                      ) : <p className="quiet">{t("review.noRevisionHistory")}</p>}
                    </details>
                    {canWrite && <button type="button" className="secondary" onClick={() => { setRelationshipDraft({ ...relationship }); setRelationshipReason(""); setError(""); }}>
                      {t("review.editRelationship")}
                    </button>}
                    {relationshipDraft?.id === relationship.id && (
                      <form onSubmit={saveRelationship} className="clinical-card">
                        <fieldset disabled={busyId === relationship.id}>
                          <legend>{t("review.editRelationship")}</legend>
                          <label>
                            {t("review.relationshipType")}
                            <input value={relationshipDraft.relationship_type} onChange={(event) => setRelationshipDraft({ ...relationshipDraft, relationship_type: event.target.value })} maxLength={50} required/>
                          </label>
                          <label>
                            {t("review.relationshipCorrectionReason")}
                            <textarea required value={relationshipReason} onChange={(event) => setRelationshipReason(event.target.value)} minLength={1} maxLength={5000} rows={3}/>
                          </label>
                          <button type="submit" className="primary" disabled={!relationshipReason.trim() || busyId === relationship.id}>{t("review.saveRelationshipCorrection")}</button>
                          <button type="button" className="secondary" onClick={() => void retractRelationship(relationship)} disabled={!relationshipReason.trim() || busyId === relationship.id}>{t("review.retractRelationship")}</button>
                          <button type="button" className="ghost" onClick={() => { setRelationshipDraft(null); setRelationshipReason(""); }}>{t("review.cancelEdit")}</button>
                        </fieldset>
                      </form>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </section>
  );
}
