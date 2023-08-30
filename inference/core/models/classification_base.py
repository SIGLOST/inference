from io import BytesIO
from time import perf_counter
from typing import Any, List, Union

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from inference.core.data_models import (
    ClassificationInferenceRequest,
    ClassificationInferenceResponse,
    InferenceResponse,
    InferenceResponseImage,
    MultiLabelClassificationInferenceResponse,
)
from inference.core.models.mixins import ClassificationMixin
from inference.core.models.roboflow import OnnxRoboflowInferenceModel
from inference.core.utils.image_utils import load_image


class ClassificationBaseOnnxRoboflowInferenceModel(
    OnnxRoboflowInferenceModel, ClassificationMixin
):
    """Base class for ONNX models for Roboflow classification inference.

    Attributes:
        multiclass (bool): Whether the classification is multi-class or not.

    Methods:
        get_infer_bucket_file_list() -> list: Get the list of required files for inference.
        softmax(x): Compute softmax values for a given set of scores.
        infer(request: ClassificationInferenceRequest) -> Union[List[Union[ClassificationInferenceResponse, MultiLabelClassificationInferenceResponse]], Union[ClassificationInferenceResponse, MultiLabelClassificationInferenceResponse]]: Perform inference on a given request and return the response.
        draw_predictions(inference_request, inference_response): Draw prediction visuals on an image.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the model, setting whether it is multiclass or not."""
        super().__init__(*args, **kwargs)
        self.multiclass = self.environment.get("MULTICLASS", False)

    def draw_predictions(self, inference_request, inference_response):
        """Draw prediction visuals on an image.

        This method overlays the predictions on the input image, including drawing rectangles and text to visualize the predicted classes.

        Args:
            inference_request: The request object containing the image and parameters.
            inference_response: The response object containing the predictions and other details.

        Returns:
            bytes: The bytes of the visualized image in JPEG format.
        """
        image = load_image(inference_request.image)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        if isinstance(inference_response.predictions, list):
            prediction = inference_response.predictions[0]
            color = self.colors.get(prediction.class_name, "#4892EA")
            draw.rectangle(
                [0, 0, image.size[1], image.size[0]],
                outline=color,
                width=inference_request.visualization_stroke_width,
            )
            text = f"{prediction.class_id} - {prediction.class_name} {prediction.confidence:.2f}"
            text_size = font.getbbox(text)

            # set button size + 10px margins
            button_size = (text_size[2] + 20, text_size[3] + 20)
            button_img = Image.new("RGBA", button_size, color)
            # put text on button with 10px margins
            button_draw = ImageDraw.Draw(button_img)
            button_draw.text((10, 10), text, font=font, fill=(255, 255, 255, 255))

            # put button on source image in position (0, 0)
            image.paste(button_img, (0, 0))
        else:
            if len(inference_response.predictions) > 0:
                box_color = "#4892EA"
                draw.rectangle(
                    [0, 0, image.size[1], image.size[0]],
                    outline=box_color,
                    width=inference_request.visualization_stroke_width,
                )
            row = 0
            predictions = [
                (cls_name, pred)
                for cls_name, pred in inference_response.predictions.items()
            ]
            predictions = sorted(
                predictions, key=lambda x: x[1].confidence, reverse=True
            )
            for i, (cls_name, pred) in enumerate(predictions):
                color = self.colors.get(cls_name, "#4892EA")
                text = f"{cls_name} {pred.confidence:.2f}"
                text_size = font.getbbox(text)

                # set button size + 10px margins
                button_size = (text_size[2] + 20, text_size[3] + 20)
                button_img = Image.new("RGBA", button_size, color)
                # put text on button with 10px margins
                button_draw = ImageDraw.Draw(button_img)
                button_draw.text((10, 10), text, font=font, fill=(255, 255, 255, 255))

                # put button on source image in position (0, 0)
                image.paste(button_img, (0, row))
                row += button_size[1]

        buffered = BytesIO()
        image = image.convert("RGB")
        image.save(buffered, format="JPEG")
        return buffered.getvalue()

    def get_infer_bucket_file_list(self) -> list:
        """Get the list of required files for inference.

        Returns:
            list: A list of required files for inference, e.g., ["environment.json"].
        """
        return ["environment.json"]

    def infer(
        self,
        image: Any,
        return_image_dims: bool = False,
        **kwargs,
    ):
        """Perform inference on a given request and return the response.

        Args:
            request (ClassificationInferenceRequest): The request object containing the image(s) and parameters for inference.

        Returns:
            Union[List[Union[ClassificationInferenceResponse, MultiLabelClassificationInferenceResponse]], Union[ClassificationInferenceResponse, MultiLabelClassificationInferenceResponse]]: The response object containing predictions, visualization, and other details.
        """
        t1 = perf_counter()

        if isinstance(image, list):
            imgs_with_dims = [self.preproc_image(i) for i in image]
            imgs, img_dims = zip(*imgs_with_dims)
            img_in = np.concatenate(imgs, axis=0)
            unwrap = False
        else:
            img_in, img_dims = self.preproc_image(image)
            img_dims = [img_dims]
            unwrap = True

        img_in /= 255.0

        mean = (0.5, 0.5, 0.5)
        std = (0.5, 0.5, 0.5)

        img_in = img_in.astype(np.float32)

        img_in[:, 0, :, :] = (img_in[:, 0, :, :] - mean[0]) / std[0]
        img_in[:, 1, :, :] = (img_in[:, 1, :, :] - mean[1]) / std[1]
        img_in[:, 2, :, :] = (img_in[:, 2, :, :] - mean[2]) / std[2]

        predictions = self.onnx_session.run(None, {self.input_name: img_in})

        if return_image_dims:
            return predictions, img_dims
        else:
            return predictions

    def infer_from_request(
        self,
        request: ClassificationInferenceRequest,
    ) -> Union[List[InferenceResponse], InferenceResponse]:
        t1 = perf_counter()
        predictions_data = self.infer(**request.dict(), return_image_dims=True)
        responses = self.make_response(
            *predictions_data,
            confidence=request.confidence,
        )
        for response in responses:
            response.time = perf_counter() - t1

        if request.visualize_predictions:
            for response in responses:
                response.visualization = self.draw_predictions(request, response)

        if not isinstance(request.image, list):
            responses = responses[0]

        return responses

    def make_response(
        self,
        predictions,
        img_dims,
        confidence: float = 0.5,
        **kwargs,
    ) -> Union[ClassificationInferenceResponse, List[ClassificationInferenceResponse]]:
        responses = []
        confidence_threshold = float(confidence)
        for ind, prediction in enumerate(predictions):
            if self.multiclass:
                preds = prediction[0]
                results = dict()
                predicted_classes = []
                for i, o in enumerate(preds):
                    cls_name = self.class_names[i]
                    score = float(o)
                    results[cls_name] = {"confidence": score, "class_id": i}
                    if score > confidence_threshold:
                        predicted_classes.append(cls_name)
                response = MultiLabelClassificationInferenceResponse(
                    image=InferenceResponseImage(
                        width=img_dims[ind][0], height=img_dims[ind][1]
                    ),
                    predicted_classes=predicted_classes,
                    predictions=results,
                )
            else:
                preds = prediction[0]
                preds = self.softmax(preds)
                results = []
                for i, cls_name in enumerate(self.class_names):
                    score = float(preds[i])
                    pred = {
                        "class_id": i,
                        "class": cls_name,
                        "confidence": round(score, 4),
                    }
                    results.append(pred)
                results = sorted(results, key=lambda x: x["confidence"], reverse=True)

                response = ClassificationInferenceResponse(
                    image=InferenceResponseImage(
                        width=img_dims[ind][1], height=img_dims[ind][0]
                    ),
                    predictions=results,
                    top=results[0]["class"],
                    confidence=results[0]["confidence"],
                )
            responses.append(response)

        return responses

    @staticmethod
    def softmax(x):
        """Compute softmax values for each set of scores in x.

        Args:
            x (np.array): The input array containing the scores.

        Returns:
            np.array: The softmax values for each set of scores.
        """
        e_x = np.exp(x - np.max(x))
        return e_x / e_x.sum()
