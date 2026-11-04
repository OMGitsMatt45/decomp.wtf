//! MIT fixtures supplied by the pinned Kirikae testkit.
fn main() {
    let root = std::path::PathBuf::from(std::env::args().nth(1).unwrap());
    std::fs::create_dir_all(&root).unwrap();
    for (name, raw) in [("hello", kirikae_testkit::hello_nro()),
        ("threads", kirikae_testkit::threads_nro()), ("parallel-threads", kirikae_testkit::parallel_threads_nro())] {
        std::fs::write(root.join(format!("{name}.nro")), raw).unwrap();
    }
}
