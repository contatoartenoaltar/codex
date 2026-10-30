# Reconhecimento local em português

`por.traineddata` é o modelo oficial do Tesseract `tessdata_fast`, obtido em
https://github.com/tesseract-ocr/tessdata_fast/blob/main/por.traineddata.
Licença Apache 2.0 em `LICENSE`. O arquivo é dado do OCR, não uma credencial.

É necessário o executável gratuito `tesseract` na hospedagem. A ativação verifica
sua presença. Não há uso de APIs de IA pagas. A rotina recebe uma imagem por vez,
com tempo limitado e uma thread. Leituras incertas e fotos apenas semelhantes
ficam para revisão; não são classificadas pelo nome genérico do arquivo.
