#pragma once

#include "CoreMinimal.h"
#include "Misc/FileHelper.h"

/**
 * Writing an artefact.
 *
 * Every file the dump emits is checked in, and the workspace convention is CRLF. Perforce
 * translates on submit, so a file written with LF stores identical bytes and nothing is lost -
 * but until it is submitted, every regenerated file reads as a whole-file rewrite in p4 diff.
 * A 12,000 line artefact reported 12,080 changed lines when one line had actually changed, and
 * the real edit is unfindable in a review that looks like that.
 *
 * So the conversion lives here rather than at the twenty call sites, where a new writer would
 * have to remember it. It is idempotent: text that already uses CRLF is unchanged, which is what
 * makes it safe to apply to a payload assembled from mixed sources.
 */
namespace AgentMemoryFile
{
	/** Saves Text with CRLF line endings. Arguments match FFileHelper::SaveStringToFile. */
	inline bool SaveStringToFileCRLF(const FString& Text, const TCHAR* Path,
		FFileHelper::EEncodingOptions EncodingOptions = FFileHelper::EEncodingOptions::AutoDetect)
	{
		FString Normalised = Text;
		// CRLF explicitly, not LINE_TERMINATOR: the target is the workspace convention, which is the
		// same whatever platform the commandlet happens to run on.
		Normalised.ReplaceInline(TEXT("\r\n"), TEXT("\n"), ESearchCase::CaseSensitive);
		Normalised.ReplaceInline(TEXT("\n"), TEXT("\r\n"), ESearchCase::CaseSensitive);
		return FFileHelper::SaveStringToFile(Normalised, Path, EncodingOptions);
	}
}
