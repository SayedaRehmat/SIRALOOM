export async function attemptSignOut(signOutAction) {
  try {
    await signOutAction();
    return true;
  } catch {
    return false;
  }
}
