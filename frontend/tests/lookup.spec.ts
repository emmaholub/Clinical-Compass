import { test, expect } from '@playwright/test';

// Opt-in: these tests use public medical APIs and billable Portkey calls.
test.skip(process.env.LIVE_EVIDENCE_TESTS !== '1', 'Set LIVE_EVIDENCE_TESTS=1 with both servers running.');

for (const [disease, firstLine] of [
  ['rheumatoid arthritis', 'methotrexate'],
  ['type 2 diabetes', 'metformin'],
  ["alzheimer's", 'donepezil'],
]) {
  test(`populates treatment evidence for ${disease}`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/');
    await page.getByLabel('What condition would you like to understand?').fill(disease);
    const responsePromise = page.waitForResponse(r => r.url().includes('/api/disease/'), { timeout: 225_000 });
    await page.getByRole('button', { name: 'Explore' }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const data = await response.json();
    await testInfo.attach('lookup-results', { body: JSON.stringify(data, null, 2), contentType: 'application/json' });
    expect(data.standard_of_care.error).toBeUndefined();
    expect(data.standard_of_care.drug_names.map((d: string) => d.toLowerCase())).toContain(firstLine);
    expect(data.standard_of_care.efficacy).toBeTruthy();
    expect(data.label_safety.treatments.length).toBeGreaterThan(0);
    expect(data.label_safety.treatments[0].common_side_effects.length).toBeGreaterThan(0);
    expect(data.alternative_treatments.treatments.length).toBeGreaterThan(0);
    for (const t of data.alternative_treatments.treatments) {
      expect(t.common_side_effects.length).toBeGreaterThan(0);
      expect(t.label_url).toContain('dailymed.nlm.nih.gov');
    }
    if (disease !== 'rheumatoid arthritis') expect(data.label_safety.treatments[0].discontinuation_rate).toBeTruthy();
    const safety = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Safety of standard treatment', exact: true }) });
    await expect(safety.getByRole('heading', { name: new RegExp(`^${firstLine}$`, 'i') })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Other common treatments', exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  });
}
