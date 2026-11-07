// Compile the same metadata lookup and full-byte validator used by the native
// entry guard, without linking the unrelated game/Cargo ABI into the test.
#[path = "../../src/decompnet/switch_native/desktop/native_entries.rs"]
mod native_entries;
