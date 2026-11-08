/** The real stages of the decoder, shown one by one while a recording is processed. */
export const PROCESSING_STEPS = [
  'Reading the EEG recording',
  'Finding blinks, eye movements and electrode pops',
  'Removing eye-muscle activity from every channel',
  'Detecting jaw clenches',
  'Turning clench timing into Morse code',
  'Correcting words and adding punctuation',
] as const;

/** Time each stage stays on screen, so the steps can be followed. */
export const STEP_MS = 1100;
export const STEP_MS_REDUCED_MOTION = 250;
