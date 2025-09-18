#include <vector>
#include <cmath>
#include <cstring>
#include <algorithm>

// Define PI if not available
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

extern "C" {

// ---------------- PitchShifter struct ----------------
struct PitchShifter {
    int window_size;
    int hop_size;
    float pitch_factor;
    std::vector<float> input_buffer;
    std::vector<float> output_buffer;
    int input_pos;
    int output_pos;
};

// ---------------- Hann window ----------------
inline float hann(int n, int N) {
    return 0.5f * (1.0f - cosf(2.0f * M_PI * n / (N - 1)));
}

// ---------------- Export macros ----------------
#if defined(_WIN32) || defined(_WIN64)
    #define EXPORT __declspec(dllexport)
#else
    #define EXPORT
#endif

// ---------------- Create / Destroy ----------------
EXPORT PitchShifter* ps_create(float pitch_factor, int window_size=512) {
    PitchShifter* ps = new PitchShifter;
    ps->window_size = window_size;
    ps->hop_size = window_size / 4;
    ps->pitch_factor = pitch_factor;
    ps->input_buffer.resize(window_size * 2, 0.0f);
    ps->output_buffer.resize(window_size * 2, 0.0f);
    ps->input_pos = 0;
    ps->output_pos = 0;
    return ps;
}

EXPORT void ps_destroy(PitchShifter* ps) {
    delete ps;
}

// ---------------- Process ----------------
EXPORT void ps_process(PitchShifter* ps, float* in, float* out, int length) {
    int N = ps->window_size;
    int H = ps->hop_size;

    for (int n = 0; n < length; ++n) {
        // write input to buffer
        ps->input_buffer[ps->input_pos % ps->input_buffer.size()] = in[n];

        // Read from buffer with pitch factor
        float pos = ps->output_pos * ps->pitch_factor;
        int idx = static_cast<int>(pos);
        float frac = pos - idx;

        float sample = 0.0f;
        if (idx < static_cast<int>(ps->input_buffer.size()) - 1)
            sample = ps->input_buffer[idx] * (1 - frac) + ps->input_buffer[idx + 1] * frac;
        else
            sample = ps->input_buffer.back();

        // Overlap-add using Hann window
        float w = hann(ps->output_pos % N, N);
        out[n] = sample * w;

        ps->input_pos++;
        ps->output_pos++;
    }
}

} // extern "C"
