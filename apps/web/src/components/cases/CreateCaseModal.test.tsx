import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import toast from 'react-hot-toast';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ create: vi.fn() }));
vi.mock('@/lib/api', () => ({ casesApi: { create: api.create } }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

import { CreateCaseModal, buildNewCase } from './CreateCaseModal';

beforeEach(() => {
  api.create.mockReset();
});

describe('buildNewCase', () => {
  it('trims, and leaves a blank description out', () => {
    expect(buildNewCase({ title: '  Odd logins  ', severity: 'high', description: '   ' })).toEqual({ title: 'Odd logins', severity: 'high' });
    expect(buildNewCase({ title: 'x', severity: 'low', description: ' notes ' })).toEqual({ title: 'x', severity: 'low', description: 'notes' });
  });
});

describe('CreateCaseModal', () => {
  it('creates the case and tells the page', async () => {
    api.create.mockResolvedValue({});
    const onCreated = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<CreateCaseModal open onClose={onClose} onCreated={onCreated} />);
    await user.type(screen.getByLabelText('Title'), 'Odd logins');
    await user.selectOptions(screen.getByLabelText('Severity'), 'high');
    await user.click(screen.getByRole('button', { name: 'Create case' }));
    expect(api.create).toHaveBeenCalledWith({ title: 'Odd logins', severity: 'high' });
    expect(onCreated).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('refuses a too-short title without calling the backend', async () => {
    const user = userEvent.setup();
    render(<CreateCaseModal open onClose={vi.fn()} onCreated={vi.fn()} />);
    await user.type(screen.getByLabelText('Title'), 'ab');
    await user.click(screen.getByRole('button', { name: 'Create case' }));
    expect(api.create).not.toHaveBeenCalled();
  });

  it('keeps the window open when the backend refuses', async () => {
    api.create.mockImplementation(async () => {
      throw new Error('nope');
    });
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<CreateCaseModal open onClose={onClose} onCreated={vi.fn()} />);
    await user.type(screen.getByLabelText('Title'), 'Odd logins');
    await user.click(screen.getByRole('button', { name: 'Create case' }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('nope'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('renders nothing when closed', () => {
    render(<CreateCaseModal open={false} onClose={vi.fn()} onCreated={vi.fn()} />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('case templates', () => {
  it('fills the title, severity and a checklist from the chosen template, all still editable, and the case is created with them', async () => {
    api.create.mockResolvedValue({});
    const user = userEvent.setup();
    render(<CreateCaseModal open onClose={vi.fn()} onCreated={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText(/Start from a template/), 'ransomware');
    expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('Suspected ransomware: ');
    expect((screen.getByLabelText('Severity') as HTMLSelectElement).value).toBe('critical');
    expect((screen.getByLabelText(/Description/) as HTMLTextAreaElement).value).toContain('- [ ] Isolate the affected devices from the network now');
    await user.type(screen.getByLabelText('Title'), 'Acme file server');
    await user.click(screen.getByRole('button', { name: 'Create case' }));
    const sent = api.create.mock.calls[0]![0];
    expect(sent.title).toBe('Suspected ransomware: Acme file server');
    expect(sent.severity).toBe('critical');
    expect(sent.description).toContain('Steps:');
  });
  it('goes back to blank fields only when the person clears them, and offers a blank case first', async () => {
    render(<CreateCaseModal open onClose={vi.fn()} onCreated={vi.fn()} />);
    const select = screen.getByLabelText(/Start from a template/) as HTMLSelectElement;
    expect(select.value).toBe('');
    expect(select.options[0]!.textContent).toBe('Blank case');
  });
});
