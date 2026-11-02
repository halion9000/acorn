'use client';

/**
 * Settings > Workspace > Members: change one person. Display name, built-in role, the custom roles they hold, and the actions an administrator needs: reset the password, end their sessions,
 * remove their passkeys (reset MFA), disable or enable, delete. Every change goes through the server, which has the last word (nobody changes their own role, disables or deletes themselves, or
 * leaves the workspace without an administrator) and says why when it refuses; that message is shown as it is.
 */
import { useState } from 'react';
import toast from 'react-hot-toast';

import { apiErrorDetail, tenantsApi, type CustomRole, type TenantUser } from '@/lib/api';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { CUSTOM_PREFIX, MEMBER_ROLES, MIN_PASSWORD_LENGTH, generatePassword } from './AddMemberForm';
import { Field, inputClass } from './panel-parts';

type Pending = null | 'mfa' | 'signout' | 'disable' | 'delete';

/** The dropdown's "leave as it is" choice, for a person whose current mix of built-in and custom roles is not one single choice. */
const KEEP = '__keep';

const BUTTON = 'rounded-lg border border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-200 hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50';

export function MemberEditor({
  member,
  isSelf,
  customRoles,
  onChanged,
  onClose,
}: {
  member: TenantUser;
  isSelf: boolean;
  customRoles: CustomRole[];
  /** Something changed on the server: reload the list. `gone` is true after a delete. */
  onChanged: (gone?: boolean) => void;
  onClose: () => void;
}) {
  const current = member.custom_roles ?? [];
  // One dropdown holds every role. A custom role is held on top of Viewer (what Add member does), so a person with exactly that is shown as the custom role; any other mix (several custom roles, or a custom role on top of a higher built-in role) is shown as "keep as it is" until a different choice is made.
  const initialChoice = current.length === 0 ? member.role : current.length === 1 && member.role === 'viewer' ? CUSTOM_PREFIX + current[0].id : KEEP;
  const mixLabel = `${MEMBER_ROLES.find((r) => r.value === member.role)?.label ?? member.role} + ${current.map((r) => r.name).join(', ')}`;
  const [displayName, setDisplayName] = useState(member.username ?? '');
  const [choice, setChoice] = useState(initialChoice);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [newPassword, setNewPassword] = useState('');
  const [passwordShown, setPasswordShown] = useState<string | null>(null);

  const knownRole = MEMBER_ROLES.some((r) => r.value === member.role);
  const dirty = displayName.trim() !== (member.username ?? '') || choice !== initialChoice;

  // One place for "call the server, show its answer": a failure keeps the dialog's message on screen, a success reloads the list.
  const act = async (what: () => Promise<{ detail?: string } | unknown>, success: string, gone = false) => {
    setBusy(true);
    setError(null);
    try {
      const result = (await what()) as { detail?: string } | undefined;
      toast.success(result && typeof result === 'object' && 'detail' in result && result.detail ? String(result.detail) : success);
      setPending(null);
      onChanged(gone);
      return true;
    } catch (err) {
      setPending(null);
      setError(apiErrorDetail(err) ?? 'That did not work. Try again.');
      return false;
    } finally {
      setBusy(false);
    }
  };

  // What the choice means for the server: a built-in role clears any custom roles; a custom role is held on top of Viewer; "keep" changes neither.
  const roleChange = (): { role?: string; custom_role_ids?: string[] } => {
    if (choice === initialChoice || choice === KEEP) return {};
    if (choice.startsWith(CUSTOM_PREFIX)) return { ...(member.role !== 'viewer' ? { role: 'viewer' } : {}), custom_role_ids: [choice.slice(CUSTOM_PREFIX.length)] };
    return { ...(choice !== member.role ? { role: choice } : {}), ...(current.length > 0 ? { custom_role_ids: [] } : {}) };
  };

  const save = () => act(() => tenantsApi.updateUser(member.id, { username: displayName.trim() || undefined, ...roleChange() }), 'Saved');

  const resetPassword = async () => {
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setError(`Use at least ${MIN_PASSWORD_LENGTH} characters for the new password.`);
      return;
    }
    const ok = await act(() => tenantsApi.resetUserPassword(member.id, newPassword), 'Password reset');
    if (ok) {
      setPasswordShown(newPassword);
      setNewPassword('');
    }
  };

  const name = member.username || member.account_name;

  return (
    <div role="group" aria-label={`Edit ${name}`} className="space-y-4 border-t border-gray-800 bg-gray-950/60 px-4 py-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Display name" hint="Shown in cases and audit. The account name they sign in with cannot be changed here.">
          <input className={inputClass()} value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoComplete="off" />
        </Field>
        <Field
          label="Role"
          hint={
            isSelf
              ? 'You cannot change your own role.'
              : choice.startsWith(CUSTOM_PREFIX)
                ? customRoles.find((r) => CUSTOM_PREFIX + r.id === choice)?.description || 'A role your workspace made. They also hold the Viewer role.'
                : choice === KEEP
                  ? 'Pick a role to replace this mix.'
                  : MEMBER_ROLES.find((r) => r.value === choice)?.hint
          }
        >
          <select className={inputClass()} value={choice} disabled={isSelf} onChange={(e) => setChoice(e.target.value)}>
            {choice === KEEP || initialChoice === KEEP ? <option value={KEEP}>{`Keep as it is (${mixLabel})`}</option> : null}
            {knownRole || initialChoice === KEEP ? null : <option value={member.role}>{member.role}</option>}
            <optgroup label="Built-in roles">
              {MEMBER_ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </optgroup>
            {customRoles.length > 0 ? (
              <optgroup label="Your custom roles">
                {customRoles.map((r) => (
                  <option key={r.id} value={CUSTOM_PREFIX + r.id}>
                    {r.name}
                  </option>
                ))}
              </optgroup>
            ) : null}
          </select>
        </Field>
      </div>

      {error ? (
        <p role="alert" data-testid="member-edit-error" className="text-sm text-red-300">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={!dirty || busy} onClick={() => void save()} className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-800 disabled:text-gray-500">
          {busy ? 'Working…' : 'Save changes'}
        </button>
        <button type="button" onClick={onClose} className={BUTTON}>
          Close
        </button>
      </div>

      <div className="space-y-3 border-t border-gray-800 pt-3">
        <p className="text-xs font-medium text-gray-300">Account actions</p>
        {isSelf ? (
          <p className="text-xs text-gray-500">This is you. Change your own password and passkeys under Profile; you cannot disable or delete yourself.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <label className="text-xs text-gray-400">
                New password
                <input
                  type="text"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  autoComplete="off"
                  aria-label="New password"
                  className={`${inputClass()} mt-1 w-64 font-mono`}
                />
              </label>
              <button type="button" onClick={() => setNewPassword(generatePassword())} className={BUTTON}>
                Generate
              </button>
              <button type="button" disabled={busy} onClick={() => void resetPassword()} className={BUTTON}>
                Reset password
              </button>
            </div>
            {passwordShown ? (
              <p role="status" data-testid="member-new-password" className="rounded-md border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-200">
                New password for {name}: <span className="font-mono text-gray-100 select-all">{passwordShown}</span>. Give it to them privately; it is not shown again. Their sessions were ended.
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={busy} onClick={() => setPending('signout')} className={BUTTON}>
                Sign out everywhere
              </button>
              <button type="button" disabled={busy} onClick={() => setPending('mfa')} className={BUTTON}>
                Reset MFA (remove passkeys)
              </button>
              <button type="button" disabled={busy} onClick={() => (member.is_active ? setPending('disable') : void act(() => tenantsApi.updateUser(member.id, { is_active: true }), `${name} can sign in again`))} className={BUTTON}>
                {member.is_active ? 'Disable account' : 'Enable account'}
              </button>
              <button type="button" disabled={busy} onClick={() => setPending('delete')} className={`${BUTTON} border-red-500/40 text-red-300`}>
                Delete…
              </button>
            </div>
          </>
        )}
      </div>

      <ConfirmDialog
        open={pending === 'signout'}
        title="Sign this person out everywhere?"
        message={`Every session ${name} has open ends now. They can sign in again with their password.`}
        confirmLabel="Sign out"
        busy={busy}
        onConfirm={() => void act(() => tenantsApi.signUserOut(member.id), 'Signed out everywhere')}
        onCancel={() => setPending(null)}
      />
      <ConfirmDialog
        open={pending === 'mfa'}
        title="Remove this person's passkeys?"
        message={`${name}'s enrolled passkeys stop working and their sessions end. They sign in with their password and can enrol a new passkey under Profile.`}
        confirmLabel="Remove passkeys"
        destructive
        busy={busy}
        onConfirm={() => void act(() => tenantsApi.resetUserMfa(member.id), 'Passkeys removed')}
        onCancel={() => setPending(null)}
      />
      <ConfirmDialog
        open={pending === 'disable'}
        title="Disable this account?"
        message={`${name} cannot sign in until you enable the account again. Their history stays.`}
        confirmLabel="Disable"
        destructive
        busy={busy}
        onConfirm={() => void act(() => tenantsApi.updateUser(member.id, { is_active: false }), `${name} was disabled`)}
        onCancel={() => setPending(null)}
      />
      <ConfirmDialog
        open={pending === 'delete'}
        title="Delete this person for good?"
        message={`${name} is removed from the workspace with their passkeys and roles. If cases, notes or audit entries still name them the delete is refused and you can disable them instead. This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        busy={busy}
        onConfirm={() => void act(() => tenantsApi.deleteUser(member.id), `${name} was deleted`, true)}
        onCancel={() => setPending(null)}
      />
    </div>
  );
}
