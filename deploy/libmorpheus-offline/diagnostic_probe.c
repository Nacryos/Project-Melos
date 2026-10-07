/* Experimental structured-ABI consumer; not a production service.
 * API contract: libmorpheus v0.4.2 include/morpheus/morpheus.h.
 * Diagnostic-only published options. Ignore-accents may retry breathings.
 * No generated forms, contextual ranking, inferred fields or attestation claims.
 */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <morpheus/morpheus.h>

static void json_string(const char *value, size_t capacity)
{
    putchar('"');
    for (size_t i = 0; i < capacity && value[i]; ++i) {
        unsigned char ch = (unsigned char)value[i];
        if (ch == '"' || ch == '\\') { putchar('\\'); putchar(ch); }
        else if (ch < 32 || ch > 126) printf("\\u%04x", (unsigned int)ch);
        else putchar(ch);
    }
    putchar('"');
}

static int terminated(const morpheus_analysis *a)
{
#define CHECK_TEXT(name) if (!memchr(a->name, 0, sizeof a->name)) return 0
    CHECK_TEXT(raw); CHECK_TEXT(workword); CHECK_TEXT(lemma);
    CHECK_TEXT(preverb); CHECK_TEXT(augment); CHECK_TEXT(stem);
    CHECK_TEXT(suffix); CHECK_TEXT(ending); CHECK_TEXT(crasis);
    CHECK_TEXT(dictionary_form); CHECK_TEXT(english_form);
    CHECK_TEXT(raw_preverb); CHECK_TEXT(domains);
#undef CHECK_TEXT
    return 1;
}

/* Preserve source bytes exactly; the projector can interpret Beta Code, while
 * non-ASCII dictionary/domain text remains bytes unless its encoding is known. */
#define TEXT_FIELD(name) do { \
    printf(",\"" #name "_hex\":\""); \
    for (size_t k = 0; k < sizeof a.name && a.name[k]; ++k) \
        printf("%02x", (unsigned int)(unsigned char)a.name[k]); \
    putchar('"'); \
} while (0)
#define NUMBER_FIELD(name) printf(",\"" #name "\":%" PRIu32, a.name)

int main(int argc, char **argv)
{
    _Static_assert(MORPHEUS_OPTION_HQ_DICTIONARY == 32, "Unexpected HQ option ABI");
    _Static_assert(MORPHEUS_OPTION_IGNORE_ACCENTS == 2, "Unexpected accent option ABI");
    morpheus_options options;
    const char *diagnostic_mode;
    if (argc != 2) return 2;
    if (strcmp(argv[1], "32") == 0) {
        options = MORPHEUS_OPTION_HQ_DICTIONARY;
        diagnostic_mode = "hq_dictionary";
    } else if (strcmp(argv[1], "2") == 0) {
        options = MORPHEUS_OPTION_IGNORE_ACCENTS;
        diagnostic_mode = "ignore_accents";
    } else return 2;
    char input[MORPHEUS_TEXT_CAPACITY + 2] = {0};
    morpheus_context *context = NULL;
    morpheus_result *result = NULL;
    if (!fgets(input, sizeof input, stdin)) return 2;
    size_t length = strlen(input);
    if (!length || input[length - 1] != '\n' || getchar() != EOF) return 2;
    input[--length] = 0;
    if (!length || length >= MORPHEUS_TEXT_CAPACITY) return 2;
    for (size_t i = 0; i < length; ++i)
        if (!strchr("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ*/\\=()+|_'-,", input[i])) return 2;
    if (morpheus_abi_version() != MORPHEUS_ABI_VERSION ||
            morpheus_analysis_size() != sizeof(morpheus_analysis)) return 3;
    morpheus_config config = {MORPHEUS_ABI_VERSION, sizeof config,
                              "/opt/libmorpheus/stemlib", MORPHEUS_LANGUAGE_GREEK};
    morpheus_status status = morpheus_open(&config, &context);
    if (status != MORPHEUS_OK) {
        fprintf(stderr, "open_status=%d\n", (int)status); return 4;
    }
    /* Exactly one published option, never their combination. Ignore-accents
     * deliberately permits upstream breathing fallback and is not attestation. */
    status = morpheus_analyze(context, (const uint8_t *)input, length, options, &result);
    if (status != MORPHEUS_OK) {
        fprintf(stderr, "analyze_status=%d\n", (int)status);
        morpheus_result_free(result); morpheus_close(context); return 5;
    }
    size_t count = morpheus_result_count(result);
    printf("{\"abi_version\":%u,\"options\":%" PRIu64 ",\"diagnostic_only\":true,\"diagnostic_mode\":\"%s\",\"relaxed\":%s,\"input_beta\":",
           MORPHEUS_ABI_VERSION, (uint64_t)options, diagnostic_mode, options == 2 ? "true" : "false");
    json_string(input, sizeof input);
    printf(",\"candidate_count\":%zu,\"candidates\":[", count);
    for (size_t i = 0; i < count; ++i) {
        morpheus_analysis a = {0};
        morpheus_truncated_fields truncated = 0;
        if (morpheus_result_get(result, i, &a) != MORPHEUS_OK ||
            morpheus_result_truncated_fields(result, i, &truncated) != MORPHEUS_OK ||
            truncated || a.struct_size != sizeof a || !terminated(&a)) {
            fprintf(stderr, "incomplete_analysis_at=%zu\n", i);
            morpheus_result_free(result); morpheus_close(context); return 6;
        }
        if (i) putchar(',');
        printf("{\"index\":%zu,\"truncated_fields\":0", i);
        NUMBER_FIELD(struct_size); NUMBER_FIELD(part_of_speech);
        NUMBER_FIELD(dialect); NUMBER_FIELD(geographic_region);
        NUMBER_FIELD(person); NUMBER_FIELD(number); NUMBER_FIELD(gender);
        NUMBER_FIELD(grammatical_case); NUMBER_FIELD(tense); NUMBER_FIELD(mood);
        NUMBER_FIELD(voice); NUMBER_FIELD(degree);
        TEXT_FIELD(raw); TEXT_FIELD(workword); TEXT_FIELD(lemma);
        TEXT_FIELD(preverb); TEXT_FIELD(augment); TEXT_FIELD(stem);
        TEXT_FIELD(suffix); TEXT_FIELD(ending); TEXT_FIELD(crasis);
        TEXT_FIELD(dictionary_form); TEXT_FIELD(english_form);
        TEXT_FIELD(raw_preverb); TEXT_FIELD(domains);
        printf(",\"morph_flags_hex\":\"");
        for (size_t j = 0; j < sizeof a.morph_flags; ++j)
            printf("%02x", (unsigned int)a.morph_flags[j]);
        printf("\"}");
    }
    puts("]}");
    morpheus_result_free(result); morpheus_close(context);
    return ferror(stdout) ? 7 : 0;
}
