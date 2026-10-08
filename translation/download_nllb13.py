"""Install a pinned community INT8 conversion of Meta NLLB distilled 1.3B."""
import download_model as download

download.MODEL_DIR = download.ROOT / "models/nllb-1.3b-int8"
download.REPO = 'JustFrederik/nllb-200-distilled-1.3B-ct2-int8'
download.REVISION = '30c36268408177b0fce2bfcfa205d877accd327d'
download.BASE_MODEL = "facebook/nllb-200-distilled-1.3B"
download.FILES = {'config.json': (159, '0c2f6fa2057c7264d052fb4a62ba3476eeae70487acddfa8e779a53a00cbf44c'), 'model.bin': (1381827087, '72d7533dc7a0e8f10f19a650d4e90faf9cbfa899db5411ad124bd5802bd91263'), 'sentencepiece.bpe.model': (4852054, '14bb8dfb35c0ffdea7bc01e56cea38b9e3d5efcdcb9c251d6b40538e1aab555a'), 'shared_vocabulary.txt': (2568098, 'a132a83330f45514c2476eb81d1d69b3c41762264d16ce0a7ea982e5d6c728e5')}

if __name__ == "__main__":
    download.main()
