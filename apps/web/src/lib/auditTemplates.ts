/**
 * The evidence an auditor usually asks for, framework by framework, so an audit can start from a full request list instead of a blank one. These are the common requests, not a promise of what
 * a particular auditor will want; each can be removed or changed once added. Pure data plus a helper that leaves out what an audit already has.
 */

export interface RequestTemplate {
  title: string;
}

const t = (...titles: string[]): RequestTemplate[] => titles.map((title) => ({ title }));

const TEMPLATES: Record<string, RequestTemplate[]> = {
  SOC2: t(
    'Organization chart and list of employees and contractors with start dates',
    'Information security policy and proof it was reviewed this period',
    'Evidence that all new hires were background checked',
    'Security awareness training completion for every employee',
    'Access reviews for production systems with sign-off',
    'List of terminated users and the date each one lost access',
    'Multi-factor authentication enforced on email, VPN and admin accounts',
    'Change management samples: approval and testing for sampled changes',
    'Vulnerability scan results and proof critical findings were fixed',
    'Penetration test report and remediation tracking',
    'Backup configuration and a restore test from this period',
    'Incident response plan, and tickets for each security incident this period',
    'Risk assessment for the period with owners and treatments',
    'Vendor list with security reviews for critical vendors',
    'Endpoint protection and disk encryption coverage report',
    'Logging and monitoring configuration with sample alerts and responses',
  ),
  ISO27001: t(
    'Scope statement of the information security management system',
    'Information security policy approved by management',
    'Statement of applicability',
    'Risk assessment method, risk register and treatment plan',
    'Internal audit report and corrective actions',
    'Management review minutes',
    'Asset inventory with owners and classifications',
    'Access control policy and a user access review',
    'Joiner, mover and leaver records for sampled people',
    'Security awareness and competence records',
    'Supplier security assessments for critical suppliers',
    'Incident register and lessons learned',
    'Business continuity and disaster recovery plan with a test record',
    'Backup and restore test evidence',
    'Cryptography policy and evidence of encryption in use',
    'Vulnerability and patch management records',
  ),
  'PCI-DSS': t(
    'Network diagram and cardholder data flow diagram',
    'Inventory of systems in scope for cardholder data',
    'Firewall and router rule set reviews (every six months)',
    'Evidence that vendor default passwords are changed',
    'Proof stored cardholder data is protected or not stored',
    'Encryption of cardholder data in transit',
    'Anti-malware deployment and update evidence',
    'Patch status for in-scope systems (critical patches within a month)',
    'Quarterly internal and external vulnerability scans with passing results',
    'Annual penetration test report',
    'Unique user IDs and multi-factor authentication for access to the cardholder data environment',
    'Access reviews for the cardholder data environment',
    'Audit log configuration and daily log review evidence',
    'Security awareness training records',
    'Incident response plan and its annual test',
    'Service provider list with their compliance status',
  ),
  HIPAA: t(
    'Security risk analysis for the period',
    'Risk management plan with owners and dates',
    'Privacy and security policies and proof of annual review',
    'Workforce HIPAA training records',
    'Business associate agreements for every vendor that handles health data',
    'Access control: user list, role assignments and access reviews',
    'Unique user identification and automatic logoff settings',
    'Audit log configuration and review records',
    'Encryption of devices and data in transit and at rest',
    'Backup, disaster recovery and emergency mode plans with a test record',
    'Incident and breach response procedure, and the incident log',
    'Facility access and device and media disposal records',
    'Sanction policy and any sanctions applied',
    'Contingency plan test results',
  ),
  'NIST-CSF': t(
    'Asset inventory for hardware, software and data',
    'Governance: cybersecurity policy and roles',
    'Risk assessment and risk register',
    'Access control and identity management records',
    'Security awareness training records',
    'Data security: encryption and backup evidence',
    'Continuous monitoring: logs and alert handling examples',
    'Vulnerability management scans and remediation',
    'Incident response plan and a test or real incident record',
    'Recovery plan and a restore test',
    'Supply chain: critical vendor reviews',
  ),
  'CIS-IG1': t(
    'Inventory of enterprise assets',
    'Inventory of software with unsupported software removed or justified',
    'Data protection: where sensitive data lives and how it is protected',
    'Secure configuration standard and evidence it is applied',
    'Account inventory and removal of dormant accounts',
    'Multi-factor authentication evidence for admin and remote access',
    'Automated patching evidence for operating systems and applications',
    'Audit log collection settings',
    'Email and web protection settings',
    'Anti-malware on all endpoints',
    'Tested backup and recovery evidence',
    'Network devices kept up to date and securely configured',
    'Security awareness training records',
    'Incident response contacts and process',
  ),
};

/** A framework name as a key: capitals and punctuation ignored, so "SOC 2", "soc2" and "SOC2" are one. */
const keyOf = (framework: string): string => framework.toUpperCase().replace(/[^A-Z0-9]/g, '');
const BY_KEY = new Map(Object.entries(TEMPLATES).map(([name, list]) => [keyOf(name), list]));

/** The usual requests for a framework, or an empty list when none is known (pure). */
export function templateFor(framework: string): RequestTemplate[] {
  return BY_KEY.get(keyOf(framework)) ?? [];
}

const norm = (s: string): string => s.toLowerCase().replace(/\s+/g, ' ').trim();

/** The usual requests the audit does not have yet, compared by title ignoring case and spacing (pure). */
export function missingRequests(framework: string, existingTitles: string[]): RequestTemplate[] {
  const have = new Set(existingTitles.map(norm));
  return templateFor(framework).filter((r) => !have.has(norm(r.title)));
}
