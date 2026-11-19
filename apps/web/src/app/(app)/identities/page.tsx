import { IdentitiesView } from '@/components/identities/IdentitiesView';
import { JoinersLeavers } from '@/components/identities/JoinersLeavers';

export const metadata = {
  title: 'Identities',
};

export default function IdentitiesPage() {
  return (
    <>
      <IdentitiesView />
      <JoinersLeavers />
    </>
  );
}
