"use client";

import { useCallback, useEffect, useState } from "react";

type ApiFetch = (path: string, init?: RequestInit) => Promise<any>;
type Props = { caseId: string; apiFetch: ApiFetch };
type Member = {
  id: string;
  member_identifier: string;
  relationship_to_proband?: string | null;
  sex?: string | null;
  affected_status: string;
  is_proband: boolean;
  sampled: boolean;
  specimen_id?: string | null;
};
type Relationship = {
  id: string;
  parent_member_id: string;
  child_member_id: string;
  relationship_type: string;
};

const RELATIONSHIPS = [
  "Mother",
  "Father",
  "Sibling",
  "Child",
  "Son",
  "Daughter",
  "Maternal grandparent",
  "Paternal grandparent",
  "Maternal aunt or uncle",
  "Paternal aunt or uncle",
  "Other relative",
  "Unknown",
];

export default function PedigreeIntake({ caseId, apiFetch }: Props) {
  const [members, setMembers] = useState<Member[]>([]);
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [memberIdentifier, setMemberIdentifier] = useState("");
  const [relationshipToProband, setRelationshipToProband] = useState("Mother");
  const [sex, setSex] = useState("UNKNOWN");
  const [affectedStatus, setAffectedStatus] = useState("UNKNOWN");
  const [isProband, setIsProband] = useState(false);
  const [parentMemberId, setParentMemberId] = useState("");
  const [childMemberId, setChildMemberId] = useState("");
  const [relationshipType, setRelationshipType] = useState("PARENT_CHILD");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    if (!caseId) return;
    setLoading(true);
    setError("");
    try {
      const result = await apiFetch(`/cases/${caseId}/pedigree`);
      setMembers(result.members ?? []);
      setRelationships(result.relationships ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load family pedigree");
    } finally {
      setLoading(false);
    }
  }, [apiFetch, caseId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const addMember = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await apiFetch(`/cases/${caseId}/pedigree/members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          member_identifier: memberIdentifier.trim(),
          relationship_to_proband: isProband ? null : relationshipToProband,
          sex,
          affected_status: affectedStatus,
          is_proband: isProband,
          sampled: false,
        }),
      });
      setMemberIdentifier("");
      setIsProband(false);
      setSex("UNKNOWN");
      setAffectedStatus("UNKNOWN");
      await refresh();
      setNotice("Family member added to the case pedigree.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to add family member");
    } finally {
      setSaving(false);
    }
  };

  const addRelationship = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!parentMemberId || !childMemberId || parentMemberId === childMemberId) {
      setError("Choose two different family members for the parent–child relationship.");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await apiFetch(`/cases/${caseId}/pedigree/relationships`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          parent_member_id: parentMemberId,
          child_member_id: childMemberId,
          relationship_type: relationshipType,
        }),
      });
      setParentMemberId("");
      setChildMemberId("");
      await refresh();
      setNotice("Pedigree relationship recorded.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to add pedigree relationship");
    } finally {
      setSaving(false);
    }
  };

  const memberName = (id: string) =>
    members.find(member => member.id === id)?.member_identifier ?? "Unknown member";

  return (
    <section className="panel" id="clinical-family-pedigree">
      <div className="panel-head">
        <div>
          <div className="section-kicker">PRE-ANALYSIS · FAMILY HISTORY</div>
          <h3>Family members and pedigree</h3>
          <p className="muted">Use coded member identifiers rather than names. Record each relative’s relationship and affected status; phenotype observations can then be assigned to the correct person.</p>
        </div>
        <span className="badge neutral">{members.length} members</span>
      </div>

      {error && <p className="danger-text" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      <div className="clinical-card">
        <h4>Add a family member</h4>
        <form className="m10-form-grid" onSubmit={addMember}>
          <label>Member identifier
            <input value={memberIdentifier} onChange={event => setMemberIdentifier(event.target.value)} maxLength={100} placeholder="e.g. MOTHER-1 or SIBLING-1" required />
          </label>
          <label>Relationship to proband
            <select value={relationshipToProband} onChange={event => setRelationshipToProband(event.target.value)} disabled={isProband}>
              {RELATIONSHIPS.map(value => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>Sex recorded in pedigree
            <select value={sex} onChange={event => setSex(event.target.value)}>
              <option value="UNKNOWN">Unknown / not recorded</option>
              <option value="FEMALE">Female</option>
              <option value="MALE">Male</option>
              <option value="OTHER">Other / not represented</option>
            </select>
          </label>
          <label>Affected status
            <select value={affectedStatus} onChange={event => setAffectedStatus(event.target.value)}>
              <option value="UNKNOWN">Unknown</option>
              <option value="AFFECTED">Affected</option>
              <option value="UNAFFECTED">Unaffected</option>
            </select>
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={isProband} onChange={event => setIsProband(event.target.checked)} />
            This member is the proband / primary patient
          </label>
          <div className="actions-row">
            <button className="primary" type="submit" disabled={saving || !memberIdentifier.trim()}>{saving ? "Saving…" : "Add family member"}</button>
          </div>
        </form>
      </div>

      <div className="clinical-card">
        <h4>Record a parent–child relationship</h4>
        <form className="m10-form-grid" onSubmit={addRelationship}>
          <label>Parent
            <select value={parentMemberId} onChange={event => setParentMemberId(event.target.value)} required>
              <option value="">Select parent</option>
              {members.map(member => <option key={member.id} value={member.id}>{member.member_identifier}</option>)}
            </select>
          </label>
          <label>Child
            <select value={childMemberId} onChange={event => setChildMemberId(event.target.value)} required>
              <option value="">Select child</option>
              {members.map(member => <option key={member.id} value={member.id}>{member.member_identifier}</option>)}
            </select>
          </label>
          <label>Relationship type
            <select value={relationshipType} onChange={event => setRelationshipType(event.target.value)}>
              <option value="PARENT_CHILD">Parent–child</option>
            </select>
          </label>
          <div className="actions-row">
            <button className="secondary" type="submit" disabled={saving || members.length < 2 || !parentMemberId || !childMemberId}>Add relationship</button>
          </div>
        </form>
      </div>

      <div className="clinical-card">
        <h4>Recorded family members</h4>
        {loading ? <p className="quiet">Loading pedigree…</p> : members.length === 0 ? (
          <p className="quiet">No family members recorded yet. Add the proband and relevant relatives before assigning family phenotype observations.</p>
        ) : (
          <div className="stack">
            {members.map(member => (
              <div className="keyline" key={member.id}>
                <div>
                  <strong>{member.member_identifier}</strong>
                  <div>{member.is_proband ? "Proband" : member.relationship_to_proband || "Relationship not recorded"} · {member.affected_status.replaceAll("_", " ")}</div>
                  <small>{member.sex || "Sex not recorded"}{member.sampled ? " · Sampled" : ""}</small>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {relationships.length > 0 && (
        <div className="clinical-card">
          <h4>Recorded relationships</h4>
          <div className="stack">
            {relationships.map(relationship => (
              <div className="keyline" key={relationship.id}>
                <strong>{memberName(relationship.parent_member_id)} → {memberName(relationship.child_member_id)}</strong>
                <small>{relationship.relationship_type.replaceAll("_", " ")}</small>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
