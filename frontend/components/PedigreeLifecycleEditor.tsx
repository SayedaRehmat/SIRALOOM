"use client";

import { useState, type FormEvent } from "react";
import { useLanguage } from "../lib/i18n";

type ApiFetch = (path: string, init?: RequestInit) => Promise<any>;
type Specimen = { specimen_id: string; specimen_identifier: string; specimen_type: string };
type Member = {
  id: string; member_identifier: string; relationship_to_proband?: string | null;
  sex?: string | null; affected_status: "AFFECTED" | "UNAFFECTED" | "UNKNOWN";
  is_proband: boolean; sampled: boolean; specimen_id?: string | null;
  revision_version?: number; revision_history?: Array<Record<string, any>>;
};
type Relationship = {
  id: string; parent_member_id: string; child_member_id: string;
  relationship_type: string; revision_version?: number;
  revision_history?: Array<Record<string, any>>;
};
type Props = {
  caseId: string; members: Member[]; relationships: Relationship[];
  specimens: Specimen[]; canWrite: boolean; apiFetch: ApiFetch;
  memberHistory?: Member[]; relationshipHistory?: Relationship[];
  onChanged: () => Promise<void>;
};

export default function PedigreeLifecycleEditor({
  caseId, members, relationships, specimens, canWrite, apiFetch,
  memberHistory = [], relationshipHistory = [], onChanged,
}: Props) {
  const { t } = useLanguage();
  const [memberId, setMemberId] = useState("");
  const [relationshipId, setRelationshipId] = useState("");
  const [memberDraft, setMemberDraft] = useState<Member | null>(null);
  const [memberReason, setMemberReason] = useState("");
  const [relationshipDraft, setRelationshipDraft] = useState<Relationship | null>(null);
  const [relationshipReason, setRelationshipReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const allMembers = memberHistory.length ? memberHistory : members;
  const allRelationships = relationshipHistory.length ? relationshipHistory : relationships;
  const selectedMember = allMembers.find((item) => item.id === memberId) ?? null;
  const selectedRelationship = allRelationships.find((item) => item.id === relationshipId) ?? null;
  const memberLabel = (id: string) => allMembers.find((item) => item.id === id)?.member_identifier ?? id;

  const beginMemberEdit = () => {
    if (!selectedMember) return;
    setMemberDraft({ ...selectedMember });
    setMemberReason("");
    setError("");
    setNotice("");
  };

  const saveMember = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!memberDraft || !memberReason.trim()) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await apiFetch(`/cases/${caseId}/pedigree/members/${memberDraft.id}/revisions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision_type: "CORRECTED", reason: memberReason.trim(),
          relationship_to_proband: memberDraft.relationship_to_proband || null,
          sex: memberDraft.sex || null, affected_status: memberDraft.affected_status,
          is_proband: memberDraft.is_proband,
          sampled: memberDraft.sampled || Boolean(memberDraft.specimen_id),
          specimen_id: memberDraft.specimen_id || null,
        }),
      });
      setMemberDraft(null); setMemberReason("");
      await onChanged(); setNotice(t("review.saveMemberCorrection"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to correct pedigree member.");
    } finally { setBusy(false); }
  };

  const retractMember = async () => {
    if (!selectedMember || !memberReason.trim()) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await apiFetch(`/cases/${caseId}/pedigree/members/${selectedMember.id}/revisions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision_type: "RETRACTED", reason: memberReason.trim() }),
      });
      setMemberDraft(null); setMemberReason(""); setMemberId("");
      await onChanged(); setNotice(t("review.retractMember"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to retract pedigree member.");
    } finally { setBusy(false); }
  };

  const beginRelationshipEdit = () => {
    if (!selectedRelationship) return;
    setRelationshipDraft({ ...selectedRelationship });
    setRelationshipReason("");
    setError("");
    setNotice("");
  };

  const saveRelationship = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!relationshipDraft || !relationshipReason.trim()) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await apiFetch(`/cases/${caseId}/pedigree/relationships/${relationshipDraft.id}/revisions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision_type: "CORRECTED", reason: relationshipReason.trim(),
          relationship_type: relationshipDraft.relationship_type,
        }),
      });
      setRelationshipDraft(null); setRelationshipReason("");
      await onChanged(); setNotice(t("review.saveRelationshipCorrection"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to correct pedigree relationship.");
    } finally { setBusy(false); }
  };

  const retractRelationship = async () => {
    if (!selectedRelationship || !relationshipReason.trim()) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await apiFetch(`/cases/${caseId}/pedigree/relationships/${selectedRelationship.id}/revisions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision_type: "RETRACTED", reason: relationshipReason.trim() }),
      });
      setRelationshipDraft(null); setRelationshipReason(""); setRelationshipId("");
      await onChanged(); setNotice(t("review.retractRelationship"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to retract pedigree relationship.");
    } finally { setBusy(false); }
  };

  const renderHistory = (history?: Array<Record<string, any>>) => (
    <details>
      <summary>{t("review.revisionHistory")}</summary>
      {(history ?? []).length > 1 ? (
        <ol>
          {(history ?? []).map((revision) => (
            <li key={String(revision.id)}>
              <strong>{revision.version === 1 ? t("review.originalRecord") : `${t("review.revisionVersion")} ${revision.version}`}</strong>
              {revision.reason && <p>{t("review.revisionReason")}: {revision.reason}</p>}
              {revision.recorded_by && <small>{t("review.recordedBy")}: {revision.recorded_by}</small>}
              {revision.created_at && <small>{t("review.recordedAt")}: {new Date(revision.created_at).toLocaleString()}</small>}
            </li>
          ))}
        </ol>
      ) : <p className="quiet">{t("review.noRevisionHistory")}</p>}
    </details>
  );

  return (
    <section className="clinical-section" aria-labelledby="pedigree-editor-heading">
      <div className="clinical-card">
        <h3 id="pedigree-editor-heading">{t("review.pedigreeEditor")}</h3>
        <p className="quiet">{t("review.pedigreeEditorHelp")}</p>
        {error && <p role="alert" className="danger-text">{error}</p>}
        {notice && <p role="status" aria-live="polite">{notice}</p>}
        <div className="two-column">
          <section className="clinical-card" aria-labelledby="pedigree-member-edit-heading">
            <h4 id="pedigree-member-edit-heading">{t("review.editMember")}</h4>
            <label htmlFor="pedigree-member-editor-select">{t("review.familyMember")}</label>
            <select id="pedigree-member-editor-select" value={memberId} onChange={(event) => { setMemberId(event.target.value); setMemberDraft(null); }}>
              <option value="">—</option>
              {allMembers.map((member) => <option key={member.id} value={member.id}>{member.member_identifier}{member.status === "RETRACTED" ? " · RETRACTED" : ""}</option>)}
            </select>
            {selectedMember && <>
              {renderHistory(selectedMember.revision_history)}
              {selectedMember.status !== "RETRACTED" && canWrite && !memberDraft && <button type="button" className="secondary" onClick={beginMemberEdit}>{t("review.editMember")}</button>}
              {selectedMember.status === "RETRACTED" && <p role="status">RETRACTED — historical record retained</p>}
            </>}
            {memberDraft && (
              <form onSubmit={saveMember}>
                <fieldset disabled={busy}>
                  <legend>{memberDraft.member_identifier}</legend>
                  <label>
                    {t("review.memberAffectedStatus")}
                    <select value={memberDraft.affected_status} onChange={(event) => setMemberDraft({ ...memberDraft, affected_status: event.target.value as Member["affected_status"] })}>
                      <option value="AFFECTED">AFFECTED</option><option value="UNAFFECTED">UNAFFECTED</option><option value="UNKNOWN">UNKNOWN</option>
                    </select>
                  </label>
                  <label>
                    {t("review.memberSex")}
                    <select value={memberDraft.sex ?? ""} onChange={(event) => setMemberDraft({ ...memberDraft, sex: event.target.value || null })}>
                      <option value="">UNKNOWN / NOT RECORDED</option><option value="MALE">MALE</option><option value="FEMALE">FEMALE</option><option value="UNKNOWN">UNKNOWN</option>
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
                  <label><input type="checkbox" checked={memberDraft.is_proband} onChange={(event) => setMemberDraft({ ...memberDraft, is_proband: event.target.checked })}/> {t("review.memberProband")}</label>
                  <label><input type="checkbox" checked={memberDraft.sampled} onChange={(event) => setMemberDraft({ ...memberDraft, sampled: event.target.checked })}/> {t("review.memberSampled")}</label>
                  <label>{t("review.memberCorrectionReason")}<textarea required value={memberReason} onChange={(event) => setMemberReason(event.target.value)} minLength={1} maxLength={5000} rows={3}/></label>
                  <button type="submit" className="primary" disabled={!memberReason.trim() || busy}>{t("review.saveMemberCorrection")}</button>
                  <button type="button" className="secondary" onClick={() => void retractMember()} disabled={!memberReason.trim() || busy}>{t("review.retractMember")}</button>
                  <button type="button" className="ghost" onClick={() => { setMemberDraft(null); setMemberReason(""); }}>{t("review.cancelEdit")}</button>
                </fieldset>
              </form>
            )}
          </section>
          <section className="clinical-card" aria-labelledby="pedigree-relationship-edit-heading">
            <h4 id="pedigree-relationship-edit-heading">{t("review.editRelationship")}</h4>
            <label htmlFor="pedigree-relationship-editor-select">{t("review.parentChild")}</label>
            <select id="pedigree-relationship-editor-select" value={relationshipId} onChange={(event) => { setRelationshipId(event.target.value); setRelationshipDraft(null); }}>
              <option value="">—</option>
              {allRelationships.map((relationship) => <option key={relationship.id} value={relationship.id}>{memberLabel(relationship.parent_member_id)} → {memberLabel(relationship.child_member_id)} · {relationship.relationship_type}{relationship.status === "RETRACTED" ? " · RETRACTED" : ""}</option>)}
            </select>
            {selectedRelationship && <>
              {renderHistory(selectedRelationship.revision_history)}
              {selectedRelationship.status !== "RETRACTED" && canWrite && !relationshipDraft && <button type="button" className="secondary" onClick={beginRelationshipEdit}>{t("review.editRelationship")}</button>}
              {selectedRelationship.status === "RETRACTED" && <p role="status">RETRACTED — historical record retained</p>}
            </>}
            {relationshipDraft && (
              <form onSubmit={saveRelationship}>
                <fieldset disabled={busy}>
                  <legend>{memberLabel(relationshipDraft.parent_member_id)} → {memberLabel(relationshipDraft.child_member_id)}</legend>
                  <label>{t("review.relationshipType")}<input required maxLength={50} value={relationshipDraft.relationship_type} onChange={(event) => setRelationshipDraft({ ...relationshipDraft, relationship_type: event.target.value })}/></label>
                  <label>{t("review.relationshipCorrectionReason")}<textarea required value={relationshipReason} onChange={(event) => setRelationshipReason(event.target.value)} minLength={1} maxLength={5000} rows={3}/></label>
                  <button type="submit" className="primary" disabled={!relationshipReason.trim() || busy}>{t("review.saveRelationshipCorrection")}</button>
                  <button type="button" className="secondary" onClick={() => void retractRelationship()} disabled={!relationshipReason.trim() || busy}>{t("review.retractRelationship")}</button>
                  <button type="button" className="ghost" onClick={() => { setRelationshipDraft(null); setRelationshipReason(""); }}>{t("review.cancelEdit")}</button>
                </fieldset>
              </form>
            )}
          </section>
        </div>
      </div>
    </section>
  );
}
