type SpeechResult = { isFinal: boolean; 0: { transcript: string } };

export function collectSpeechResults(results: ArrayLike<SpeechResult>, acceptedFinalIndices: Set<number>) {
  const finalTexts: string[] = [];
  let interim = "";

  for (let index = 0; index < results.length; index += 1) {
    const result = results[index];
    if (result.isFinal) {
      if (!acceptedFinalIndices.has(index)) {
        acceptedFinalIndices.add(index);
        finalTexts.push(result[0].transcript);
      }
    } else {
      interim += result[0].transcript;
    }
  }

  return { finalTexts, interim };
}
