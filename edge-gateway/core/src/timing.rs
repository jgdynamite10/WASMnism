/// Cross-platform timing that works on native, wasm32-wasi, and wasm32-unknown-unknown.
///
/// On native and WASI targets, delegates to `std::time::Instant` and `SystemTime`.
/// On `wasm32-unknown-unknown` (Cloudflare Workers), uses `js_sys::Date::now()`
/// since `std::time` panics without WASI or JS polyfills.

#[cfg(not(all(target_arch = "wasm32", not(target_os = "wasi"))))]
mod imp {
    use std::time::{Instant, SystemTime, UNIX_EPOCH};

    #[derive(Debug, Clone, Copy)]
    pub struct Timer(Instant);

    impl Timer {
        pub fn now() -> Self {
            Self(Instant::now())
        }
        pub fn elapsed_ms(&self) -> f64 {
            self.0.elapsed().as_secs_f64() * 1000.0
        }
    }

    pub fn epoch_ms() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64
    }
}

#[cfg(all(target_arch = "wasm32", not(target_os = "wasi")))]
mod imp {
    #[derive(Debug, Clone, Copy)]
    pub struct Timer(f64);

    fn perf_now() -> f64 {
        let global = js_sys::global();
        let perf = match js_sys::Reflect::get(&global, &"performance".into()) {
            Ok(v) if !v.is_undefined() => v,
            _ => return js_sys::Date::now(),
        };
        let func = match js_sys::Reflect::get(&perf, &"now".into()) {
            Ok(v) if !v.is_undefined() => js_sys::Function::from(v),
            _ => return js_sys::Date::now(),
        };
        func.call0(&perf)
            .ok()
            .and_then(|v| v.as_f64())
            .unwrap_or_else(|| js_sys::Date::now())
    }

    impl Timer {
        pub fn now() -> Self {
            Self(perf_now())
        }
        pub fn elapsed_ms(&self) -> f64 {
            perf_now() - self.0
        }
    }

    pub fn epoch_ms() -> u64 {
        js_sys::Date::now() as u64
    }
}

pub use imp::{epoch_ms, Timer};
