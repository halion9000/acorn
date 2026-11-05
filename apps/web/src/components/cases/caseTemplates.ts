import type { CaseSeverityChoice } from './CreateCaseModal';

/** A starting point for a common kind of incident: what to call it, how serious it usually is, and the steps that are easy to forget. Picking one only fills the form; everything stays editable. */
export interface CaseTemplate {
  id: string;
  label: string;
  title: string;
  severity: CaseSeverityChoice;
  steps: string[];
}

export const CASE_TEMPLATES: CaseTemplate[] = [
  {
    id: 'bec',
    label: 'Business email compromise',
    title: 'Possible business email compromise: ',
    severity: 'high',
    steps: [
      'Run the BEC search on the person (Identities page) and read the report',
      'End their sessions and block sign-in until it is understood',
      'Look for inbox rules that forward or hide mail, and for new app consents',
      'Check what was sent from the mailbox and whether any payment details changed',
      'Reset the password from a clean machine and re-check multi-factor methods',
      'Tell the client who may have received mail from the account',
    ],
  },
  {
    id: 'phishing',
    label: 'Phishing reported',
    title: 'Phishing email reported: ',
    severity: 'medium',
    steps: [
      'Find who else received the message and whether anyone clicked or replied',
      'Remove the message from every mailbox that has it',
      'Block the sender and any link or attachment hosts',
      'For anyone who clicked: check sign-ins and reset their password',
      'Tell the person who reported it what was found',
    ],
  },
  {
    id: 'ransomware',
    label: 'Ransomware or encryption',
    title: 'Suspected ransomware: ',
    severity: 'critical',
    steps: [
      'Isolate the affected devices from the network now',
      'Find the first affected device and when it started',
      'Check backups are intact and out of reach before restoring anything',
      'Preserve evidence: do not wipe or reimage yet',
      'Tell the client lead and decide who talks to insurance and legal',
    ],
  },
  {
    id: 'malware',
    label: 'Malware on a device',
    title: 'Malware detected on ',
    severity: 'high',
    steps: [
      'Confirm the detection and whether it was blocked or ran',
      'Isolate the device if it ran',
      'Check what the device and its user touched since',
      'Scan the device again and remove or rebuild it',
    ],
  },
  {
    id: 'lost-device',
    label: 'Lost or stolen device',
    title: 'Lost or stolen device: ',
    severity: 'medium',
    steps: [
      'Confirm the device was encrypted and had a screen lock',
      'Lock or wipe it remotely if the management tool allows',
      'Sign the person out everywhere and reset their password',
      'Record what data the device held',
    ],
  },
  {
    id: 'suspicious-signin',
    label: 'Suspicious sign-in',
    title: 'Suspicious sign-in: ',
    severity: 'medium',
    steps: [
      'Check the location, device and time against what the person normally does',
      'Ask the person, by phone, whether it was them',
      'If it was not: end sessions, reset the password and review recent activity',
    ],
  },
  {
    id: 'data-exposure',
    label: 'Data exposure or breach found',
    title: 'Possible data exposure: ',
    severity: 'high',
    steps: [
      'Work out what data and whose is involved',
      'Stop the exposure (remove access, rotate any exposed secret)',
      'Record when it began and who could have seen it',
      'Tell the client lead so they can decide on notification duties',
    ],
  },
];

/** The description a template gives: a plain checklist of its steps. */
export function templateDescription(t: CaseTemplate): string {
  return ['Steps:', ...t.steps.map((s) => `- [ ] ${s}`)].join('\n');
}
