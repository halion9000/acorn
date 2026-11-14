'use client';

import { useEffect } from 'react';
import { hasSignIn, startIdleWatch } from '@/lib/idle-timeout';

/** Signs the person out after four hours without activity (see lib/idle-timeout.ts). Draws nothing. Does nothing when this browser holds no saved sign-in (development without a login, demo). */
export function IdleLogout() {
  useEffect(() => {
    if (!hasSignIn()) return;
    return startIdleWatch();
  }, []);
  return null;
}
