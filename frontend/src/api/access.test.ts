import { describe, expect, it } from 'vitest';
import { gateKindFromBody } from './access';

describe('gateKindFromBody', () => {
  it('reads the access error in either body shape', () => {
    expect(gateKindFromBody(401, { error: 'access_code_required' })).toBe('access');
    expect(gateKindFromBody(401, { detail: { error: 'access_code_required' } })).toBe('access');
    expect(gateKindFromBody(401, { detail: 'access_code_required' })).toBe('access');
  });
  it('reads the reviewer error', () => {
    expect(gateKindFromBody(401, { error: 'review_code_required' })).toBe('reviewer');
    expect(gateKindFromBody(401, { error: 'reviewer_code_required' })).toBe('reviewer');
    expect(gateKindFromBody(403, { detail: 'reviewer_code_required' })).toBe('reviewer');
  });
  it('ignores other statuses and bodies', () => {
    expect(gateKindFromBody(404, { error: 'access_code_required' })).toBeNull();
    expect(gateKindFromBody(401, { detail: 'Not authenticated' })).toBeNull();
    expect(gateKindFromBody(401, null)).toBeNull();
  });
});
