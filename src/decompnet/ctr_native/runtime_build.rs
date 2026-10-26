use std::path::PathBuf;

fn main() {
    let library = PathBuf::from(std::env::var_os("CTR_GAME_LIBRARY").expect("build this project through CMake"));
    let target = std::env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    let name = if target == "msvc" { "ctr_game.lib" } else { "libctr_game.a" };
    let output = PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
    std::fs::copy(&library, output.join(name)).expect("stage generated C library");
    println!("cargo:rerun-if-env-changed=CTR_GAME_LIBRARY");
    println!("cargo:rerun-if-changed={}", library.display());
    println!("cargo:rustc-link-search=native={}", output.display());
    println!("cargo:rustc-link-lib=static=ctr_game");
    if std::env::var("CARGO_CFG_TARGET_FAMILY").as_deref() == Ok("unix") {
        println!("cargo:rustc-link-lib=m");
    }
    if target == "msvc" { println!("cargo:rustc-link-arg-bins=/STACK:8388608"); }
}
