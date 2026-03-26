use tract_onnx::prelude::*;
use tract_nnef::framework::Nnef;

fn main() -> TractResult<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        eprintln!("Usage: convert-to-nnef <input.onnx> <output.nnef.tar>");
        std::process::exit(1);
    }

    let onnx_path = &args[1];
    let nnef_path = &args[2];
    let max_length: i64 = 128;

    println!("Loading ONNX model from {onnx_path}...");
    let model = tract_onnx::onnx()
        .model_for_path(onnx_path)?
        .with_input_fact(0, InferenceFact::dt_shape(i64::datum_type(), tvec![1, max_length]))?
        .with_input_fact(1, InferenceFact::dt_shape(i64::datum_type(), tvec![1, max_length]))?
        .with_input_fact(2, InferenceFact::dt_shape(i64::datum_type(), tvec![1, max_length]))?
        .into_typed()?
        .into_decluttered()?;

    println!("Model loaded and decluttered (will be optimized at load time)");
    println!("  Nodes: {}", model.nodes().len());

    println!("Saving as NNEF to {nnef_path}...");
    let nnef = Nnef::default()
        .with_tract_core()
        .with_tract_resource()
        .with_registry(tract_onnx_opl::onnx_opl_registry());
    nnef.write_to_tar(&model, std::fs::File::create(nnef_path)?)?;

    let size = std::fs::metadata(nnef_path)?.len();
    println!("Done: {nnef_path} ({:.1} MB)", size as f64 / (1024.0 * 1024.0));

    Ok(())
}
