/** The compliance frameworks A.C.O.R.N has controls for. `id` names the page (/compliance/<id>); `key` is the name the API and the evidence use. */
export interface FrameworkInfo {
  id: string;
  key: string;
  name: string;
  description: string;
  badge: string;
}

export const FRAMEWORK_LIST: FrameworkInfo[] = [
  { id: 'soc2', key: 'SOC2', name: 'SOC 2 Type II', description: 'Trust Services Criteria for security, availability, and confidentiality.', badge: 'Enterprise' },
  { id: 'iso27001', key: 'ISO27001', name: 'ISO/IEC 27001:2022', description: 'International standard for information security management systems.', badge: 'International' },
  { id: 'nist_csf', key: 'NIST-CSF', name: 'NIST CSF 2.0', description: 'NIST Cybersecurity Framework covering Govern, Identify, Protect, Detect, Respond, Recover.', badge: 'US Government' },
  { id: 'pci_dss', key: 'PCI-DSS', name: 'PCI DSS v4.0', description: 'Payment Card Industry Data Security Standard for cardholder data environments.', badge: 'Financial' },
  { id: 'hipaa', key: 'HIPAA', name: 'HIPAA Security Rule', description: 'Administrative, physical, and technical safeguards for protected health information.', badge: 'Healthcare' },
  { id: 'cis_ig1', key: 'CIS-IG1', name: 'CIS Controls v8, IG1', description: 'The 56 safeguards of Implementation Group 1: essential cyber hygiene for every organization.', badge: 'Essential hygiene' },
];

export const frameworkByKey = (key: string): FrameworkInfo | undefined => FRAMEWORK_LIST.find((f) => f.key === key);
