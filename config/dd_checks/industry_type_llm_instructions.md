## Objective

Using only the provided context, classify the startup into exactly one of these industry types:

* Software
* Hardware
* Biology
* General

## Classification Definitions

### Software

The company's core product is software, such as SaaS, web or mobile applications, pure AI/ML products, FinTech, marketplaces, or software platforms. Merely using software or operating a website does not make a company Software.

### Hardware

The company's core value depends on a proprietary physical product, material, component, or device. This includes semiconductors, advanced materials, Deep Tech, robotics, drones, IoT devices, MedTech devices, and CleanTech hardware. A company that develops or sells proprietary physical components or materials is Hardware even if it also provides software or engineering services.

### Biology

The company's core product or technology depends on biological research, wet-lab work, therapeutics, pharmaceuticals, diagnostics, industrial biotechnology, life sciences, or computational biology. AI-based drug discovery is Biology rather than Software.

### General

The company does not fit the Software, Hardware, or Biology definitions. Examples include traditional services, real estate, food and beverage, conventional e-commerce, and D2C or consumer-goods businesses without a proprietary high-technology product.

## Decision Rules

1. Classify the startup itself, not its employees, advisers, customers, partners, or investors.
2. Prioritize direct descriptions of the company's product, technology, manufacturing, research, and business model.
3. Incidental references to software licenses, websites, IT systems, or employees' software experience are not evidence that the startup is Software.
4. If a proprietary physical material, component, or device is central to the value proposition, classify the startup as Hardware, even when software or services are also involved.
5. If biological or wet-lab work is central to the product, classify the startup as Biology.
6. Choose General only when the evidence supports it, not merely because another classification is uncertain.
7. If the context does not contain enough company-specific evidence to select a type, output exactly:

INSUFFICIENT_CONTEXT

## Output Format

Return the classification first, followed by a confidence score and two or three short evidence statements:

Industry Type: TYPE
Confidence Score: NN%
Evidence:
* Company-specific evidence supporting the classification.
* Additional company-specific evidence supporting the classification.

Replace TYPE with Software, Hardware, Biology, or General. Do not return multiple types.
