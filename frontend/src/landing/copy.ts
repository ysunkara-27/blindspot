// Landing copy that tests and sections share. Facts quote docs/RESEARCH.md; each carries its source.
export const FREE_LINE = 'Free · no account · about 2 minutes per film';
/** The feedback form is a page of the app now (FeedbackPage.tsx); the landing band links there. */
export const FEEDBACK_PATH = '/feedback';

export type Fact = { lead: string; text: string; source: string; url: string };
export const FACTS: Fact[] = [
  {
    lead: 'Most misses are perceptual.',
    text: 'Roughly 60–80 % of diagnostic errors in radiology are perceptual: the finding is on the image, and nobody saw it.',
    source: 'Review of diagnostic errors in radiology (PMC)',
    url: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC10545608/',
  },
  {
    lead: 'Few students are taught to look.',
    text: 'Only about 20 % of US medical schools require a radiology clerkship, unchanged from 2011 to 2018.',
    source: 'Chen & Kumaran, Int J Med Students',
    url: 'https://ijms.pitt.edu/IJMS/article/download/1987/2590',
  },
  {
    lead: 'First reads are often not by radiologists.',
    text: 'In an emergency department, physicians and residents found small pneumothoraces only half the time (49.7 %).',
    source: 'Kaymak et al., Eurasian J Emerg Med 2018',
    url: 'https://doaj.org/article/650e3dec5cb64484a6ee7134203f64d1',
  },
];

export const PROXY_CAVEAT = 'Where you looked is estimated from your cursor, magnifier and zoom: a stand-in for your eyes, not eye tracking. Treat a miss type as a strong hint, not a verdict.';
