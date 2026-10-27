import { Metadata } from 'next';
import { FrameworkIndex } from '@/components/compliance/FrameworkIndex';

export const metadata: Metadata = {
  title: 'Compliance',
};

const FRAMEWORKS = [
  {
    id: 'soc2',
    name: 'SOC 2 Type II',
    description: 'Trust Services Criteria for security, availability, and confidentiality.',
    badge: 'Enterprise',
  },
  {
    id: 'iso27001',
    name: 'ISO/IEC 27001:2022',
    description: 'International standard for information security management systems.',
    badge: 'International',
  },
  {
    id: 'nist_csf',
    name: 'NIST CSF 2.0',
    description: 'NIST Cybersecurity Framework covering Govern, Identify, Protect, Detect, Respond, Recover.',
    badge: 'US Government',
  },
  {
    id: 'pci_dss',
    name: 'PCI DSS v4.0',
    description: 'Payment Card Industry Data Security Standard for cardholder data environments.',
    badge: 'Financial',
  },
  {
    id: 'hipaa',
    name: 'HIPAA Security Rule',
    description: 'Administrative, physical, and technical safeguards for protected health information.',
    badge: 'Healthcare',
  },
];

export default function CompliancePage() {
  return <FrameworkIndex frameworks={FRAMEWORKS} />;
}
